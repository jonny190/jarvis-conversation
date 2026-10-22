"""Conversation entity that forwards a sentence to Jarvis and speaks the answer."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Final, Literal

import aiohttp

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_API_KEY,
    CONF_FALLBACK_LOCAL,
    CONF_MAX_SPOKEN_CHARS,
    CONF_MODEL,
    CONF_TIMEOUT,
    CONF_URL,
    DEFAULT_FALLBACK_LOCAL,
    DEFAULT_MAX_SPOKEN_CHARS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SESSION_ID_PREFIX,
    VOICE_BRIEF_ANSWER_SHAPE,
    VOICE_BRIEF_NO_INFERRED_EVENTS,
    VOICE_BRIEF_PINNED_EVENTS,
    VOICE_BRIEF_PINNED_FACTS,
    VOICE_BRIEF_PINNED_NAMES,
    VOICE_BRIEF_PINNED_POWER,
)
from .speech import prepare_for_tts

_LOGGER = logging.getLogger(__name__)

# Why Jarvis produced no usable answer. The spoken sentence differs per cause,
# because the four say genuinely different things about what the house just did and
# what the user should do next — whether a command may still land, whether the
# network is worth checking, and whether repeating themselves will help.
ERR_TIMEOUT: Final = "timeout"
ERR_UNREACHABLE: Final = "unreachable"
ERR_UNUSABLE: Final = "unusable"
ERR_FAILED: Final = "failed"

FALLBACK_SPEECH: Final = {
    # Giving up now disconnects the stream, which is what asks Jarvis to stop (see
    # the streaming note on _async_ask_jarvis). "Asked it to stop" is therefore true
    # where "still working" used to be. The second sentence stays because stopping
    # is cooperative: an action Jarvis had already dispatched is not recalled by it,
    # and a user who thinks nothing happened will say it again.
    ERR_TIMEOUT: (
        "Jarvis took too long, so I've asked it to stop. "
        "Anything it had already started may still have gone through."
    ),
    # Genuinely transient and genuinely about reachability, so "right now" is fair.
    ERR_UNREACHABLE: "Sorry, I can't reach Jarvis right now.",
    # Jarvis replied, but nothing in the reply was speakable.
    ERR_UNUSABLE: "Jarvis replied, but there was nothing in it to read out.",
    # Jarvis was reached and the turn ran, but it ended badly with nothing to say.
    # Distinct from UNREACHABLE: "I can't reach Jarvis" would send someone to check
    # a network that is fine.
    ERR_FAILED: "Jarvis ran into a problem with that one.",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Jarvis conversation entity."""
    async_add_entities([JarvisConversationEntity(entry)])


def _accumulate_frame(frame: dict[str, Any], parts: list[str]) -> tuple[str | None, str | None]:
    """Fold one decoded SSE frame into `parts` -> (finish_reason, error message).

    The gateway multiplexes several kinds of frame down this one stream: chat
    chunks, plus `hermes.tool.progress`, `hermes.status` and `approval.request`
    custom events. Discriminating on `object` rather than on the SSE `event:` line
    is deliberate — only chat chunks carry `object: chat.completion.chunk`, so an
    event type added to the gateway later is ignored here instead of being
    mistaken for something to say.
    """
    if frame.get("object") != "chat.completion.chunk":
        return None, None
    choices = frame.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, dict):
        return None, None
    delta = choice.get("delta")
    if isinstance(delta, dict):
        piece = delta.get("content")
        # `content` only. `reasoning_content` rides the same stream as
        # `delta.reasoning_content` and is Jarvis's private monologue: it must
        # never reach text-to-speech, and on a per-character voice it would also
        # be the single most expensive thing in the reply.
        if isinstance(piece, str):
            parts.append(piece)
    error = frame.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    return choice.get("finish_reason"), message


async def _async_collect_stream(resp: Any) -> tuple[str, str | None, str | None]:
    """Read one SSE response to the end -> (text, finish_reason, error message).

    Caller-cancellable by construction: it awaits the socket line by line, so the
    `asyncio.timeout` around it can cut in at any point, which is the whole reason
    this integration streams at all.
    """
    parts: list[str] = []
    finish_reason: str | None = None
    stream_error: str | None = None
    data: list[str] = []

    async for raw in resp.content:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith(":"):
            continue  # ": keepalive" — the frame that makes a hangup detectable
        if line:
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            # "event:" / "id:" lines need no handling; see _accumulate_frame.
            continue
        # Blank line: end of frame.
        if not data:
            continue
        payload, data = "\n".join(data), []
        if payload == "[DONE]":
            break
        try:
            frame = json.loads(payload)
        except ValueError:
            _LOGGER.debug("Skipping unparseable SSE frame: %.120s", payload)
            continue
        if not isinstance(frame, dict):
            continue
        reason, message = _accumulate_frame(frame, parts)
        finish_reason = reason or finish_reason
        stream_error = message or stream_error

    return "".join(parts), finish_reason, stream_error


class JarvisConversationEntity(conversation.ConversationEntity):
    """Speaks to Jarvis over its OpenAI-compatible gateway.

    Jarvis is an agent, not a model: it runs its own tool loop and performs Home
    Assistant actions itself, under its own `jarvis` token. Nothing this entity sends
    constrains that — client-supplied `tools` are ignored by the gateway (verified
    against the running hermes-agent source, DAV-24). This entity therefore does three
    jobs only: give Jarvis the room context it needs, make sure a slow or dead Jarvis
    can never wedge the voice pipeline, and decide what of Jarvis's reply is fit to
    say out loud (see speech.py — the gateway returns chat text, not a script).
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supports_streaming = False

    # Deliberately NOT ConversationEntityFeature.CONTROL.
    #
    # In 2026.9.0 the pipeline narrows local intent handling to GET_STATE and
    # MEDIA_SEARCH_AND_PLAY *only when the agent declares CONTROL*
    # (_async_local_fallback_intent_filter in assist_pipeline/pipeline.py). Declaring
    # CONTROL therefore routes virtually every spoken sentence to Jarvis: ~46.5k input
    # tokens and ~5.5 s per utterance, including "turn the kitchen light off" that the
    # local matcher answers instantly and for free. Leaving it unset keeps the
    # preferred pipeline's `prefer_local_intents: true` behaviour intact and sends
    # Jarvis only what the local matcher could not understand.
    #
    # One-line flip if the household decides otherwise:
    #   _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_supported_features = conversation.ConversationEntityFeature(0)

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialise the entity from its config entry."""
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Jarvis",
            manufacturer="Daveys Home",
            model="hermes-agent",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last_error: str | None = None
        self._last_latency: float | None = None
        self._fallback_count = 0

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Jarvis is not language-restricted."""
        return MATCH_ALL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose enough to see failures without reading the log."""
        return {
            "last_latency_seconds": self._last_latency,
            "last_error": self._last_error,
            "fallback_count": self._fallback_count,
        }

    # --- options -------------------------------------------------------------

    def _option(self, key: str, default: Any) -> Any:
        return self._entry.options.get(key, self._entry.data.get(key, default))

    def _int_option(self, key: str, default: int) -> int:
        """An options-flow number arrives as a float, and could be anything at all.

        This runs inside the turn, where _async_ask_jarvis promises never to raise,
        so a malformed stored option must degrade to the default rather than take
        voice down with it.
        """
        try:
            return int(float(self._option(key, default)))
        except (TypeError, ValueError):
            _LOGGER.warning("Ignoring unusable %s option; using %s", key, default)
            return default

    # --- the turn ------------------------------------------------------------

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Run one voice turn."""
        # Discriminate on `cause`, not on `text`: it is the tag that tells both the
        # type checker and the reader which half of the return union this is.
        text, cause, detail = await self._async_ask_jarvis(user_input)

        if cause is not None:
            self._last_error = detail
            self._fallback_count += 1
            self.async_write_ha_state()
            return await self._async_fallback(user_input, chat_log, cause, detail)

        self._last_error = None
        self.async_write_ha_state()

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=user_input.agent_id, content=text)
        )
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(text)
        return conversation.ConversationResult(
            response=response,
            conversation_id=chat_log.conversation_id,
            continue_conversation=chat_log.continue_conversation,
        )

    async def _async_ask_jarvis(
        self, user_input: conversation.ConversationInput
    ) -> tuple[str, None, None] | tuple[None, str, str]:
        """Return (spoken text, None, None) or (None, cause, detail). Never raises.

        `cause` is one of the ERR_* constants and picks the spoken sentence;
        `detail` is the long form for the log and the entity attribute.

        This asks for `"stream": True` and then does NOT stream: the whole reply is
        collected here and handed back in one piece, exactly as the buffered request
        in 0.1.1 did. The entity still declares `_attr_supports_streaming = False`,
        so nothing is spoken early and the user-visible behaviour is unchanged.

        The reason for streaming is cancellation, not responsiveness. On the
        gateway's buffered path (`_handle_chat_completions`, non-streaming tail) the
        turn is `await`ed out of a thread executor and the client is never consulted
        again: aiohttp is built with `handler_cancellation` left at its default of
        False, so hanging up tells the gateway nothing and the agent runs to
        completion regardless. Measured against that path on the gateway's own
        aiohttp 3.14.3: client gives up at 12 s, server never notices, turn finishes
        at 40 s. That is the mechanism behind the driveway light that actuated 232 s
        after the client had gone (DAV-25).

        The gateway's SSE writer does check. It catches the disconnect, calls
        `_abandon_agent_task` -> `request_hard_interrupt`, and reaps the turn's
        background processes. Because it emits a `: keepalive` comment every 10 s
        even while the agent is silent mid-tool-call, it finds out within one
        keepalive interval of the hangup at worst, and on the next token at best.
        Same measurement, streaming path: hangup at 12 s, detected at 20 s.

        Two things this does not buy, both of which the spoken timeout wording has
        to keep covering. The interrupt is cooperative, so Jarvis stops at its next
        checkpoint rather than instantly; and a tool call already dispatched -- the
        Home Assistant service call that turns the light on -- is not recalled by
        stopping the loop that issued it. Bounded overhang, not no overhang.
        """
        url = str(self._option(CONF_URL, "")).rstrip("/") + "/v1/chat/completions"
        timeout = float(self._option(CONF_TIMEOUT, DEFAULT_TIMEOUT))
        payload: dict[str, Any] = {
            "model": self._option(CONF_MODEL, DEFAULT_MODEL),
            "stream": True,
            "messages": [
                {"role": "system", "content": self._system_prompt(user_input)},
                {"role": "user", "content": user_input.text},
            ],
        }
        # Half of the voice profile's speed, and it costs nothing on the server. See
        # DEFAULT_REASONING_EFFORT: this is per-request, so it cannot reach the
        # Telegram, WhatsApp, CLI or cron routes even in principle.
        if DEFAULT_REASONING_EFFORT is not None:
            payload["model_options"] = {"reasoning_effort": DEFAULT_REASONING_EFFORT}
        headers = {
            "Authorization": f"Bearer {self._option(CONF_API_KEY, '')}",
            # Maps one HA conversation onto one Hermes session, so a follow-up
            # ("and the other one too") lands in the same transcript. The gateway
            # 403s this header unless API_SERVER_KEY is configured, which it is.
            "X-Hermes-Session-Id": f"{SESSION_ID_PREFIX}{user_input.conversation_id}",
        }

        session = async_get_clientsession(self.hass)
        started = time.monotonic()
        resp = None
        try:
            async with asyncio.timeout(timeout):
                resp = await session.post(url, json=payload, headers=headers)
                if resp.status != 200:
                    # A rejected request is an ordinary JSON error envelope, not SSE.
                    body = await resp.json()
                    reason = str(
                        (body or {}).get("error", {}).get("message") or resp.status
                    )
                    return (
                        None,
                        ERR_UNREACHABLE,
                        f"gateway returned {resp.status}: {reason[:200]}",
                    )
                content, finish_reason, stream_error = await _async_collect_stream(resp)
        except TimeoutError:
            # Dropping the connection is the signal. Close rather than release: the
            # body is unfinished, so this must abort the socket and not hand it back
            # to the pool for reuse.
            if resp is not None:
                resp.close()
            return None, ERR_TIMEOUT, f"no answer within {timeout:.0f}s; asked Jarvis to stop"
        except aiohttp.ClientError as err:
            if resp is not None:
                resp.close()
            return None, ERR_UNREACHABLE, f"transport error: {err}"
        except ValueError as err:  # non-JSON error body
            return None, ERR_UNREACHABLE, f"unreadable response: {err}"
        finally:
            self._last_latency = round(time.monotonic() - started, 2)

        content = content.strip()
        if not content:
            # No speakable text. Distinguish "ran and broke" from "ran and said
            # nothing": the buffered path signalled the first as a 502, which this
            # path cannot do because the 200 is already on the wire by then.
            if stream_error or finish_reason in ("error", "failed"):
                return (
                    None,
                    ERR_FAILED,
                    f"agent error ({finish_reason or 'unknown'}): "
                    f"{(stream_error or 'no detail')[:200]}",
                )
            return None, ERR_UNUSABLE, "empty answer"

        # `content` is chat text, not a script. It can carry Markdown, emoji, file
        # paths and Hermes's own turn-end advisories (DAV-28 caught the
        # file-mutation verifier footer being read aloud, file paths and all, on a
        # per-character-billed voice). Hermes runs this same cleanup before every
        # one of its own TTS calls; so do we.
        text = prepare_for_tts(
            content, self._int_option(CONF_MAX_SPOKEN_CHARS, DEFAULT_MAX_SPOKEN_CHARS)
        )
        if not text:
            # Everything in the reply was non-speech — e.g. the whole turn was a
            # verifier footer. Speaking "" would leave the user with silence and no
            # idea why, so this is a failure with a spoken reason.
            return None, ERR_UNUSABLE, f"nothing speakable in {len(content)}-char reply"
        if len(text) < len(content):
            _LOGGER.debug(
                "Trimmed reply for speech: %d chars in, %d spoken",
                len(content),
                len(text),
            )
        return text, None, None

    def _system_prompt(self, user_input: conversation.ConversationInput) -> str:
        """Carry room/satellite context and the voice brief to Jarvis.

        Order matters and is not arbitrary. Hermes appends this whole string to
        Jarvis's standing prompt as `ephemeral_system_prompt` (DAV-29 §4.3), so the
        last thing here is the last thing Jarvis reads before the question:

          1. where the request came from, and which room "here" means;
          2. the answer-shape rules, so the length constraint frames everything;
          3. the refusal rule, because it overrides the urge to be helpful that
             rules 2 and 4 otherwise encourage;
          4. the three pinned facts, nearest the question, where a specific entity
             id is most likely to be used instead of a guess.

        Anything the pipeline passes in `extra_system_prompt` still goes last: it is
        the user's own per-pipeline text and should be able to override us.
        """
        parts = [
            "This request arrived through Home Assistant Assist and your reply will be "
            "read aloud by a speaker."
        ]

        area_name: str | None = None
        if user_input.device_id:
            device = dr.async_get(self.hass).async_get(user_input.device_id)
            if device is not None:
                parts.append(f"Satellite device: {device.name_by_user or device.name}.")
                if device.area_id:
                    area = ar.async_get(self.hass).async_get_area(device.area_id)
                    if area is not None:
                        area_name = area.name

        if area_name:
            parts.append(
                f"The speaker is in the {area_name} area. Resolve 'here', 'this room' "
                f"and unqualified room references to {area_name}."
            )
        else:
            parts.append(
                "The room is unknown. If the request depends on which room it came "
                "from, ask which room rather than guessing."
            )

        parts.append(f"Spoken language: {user_input.language}.")
        parts.append(
            "Answer in one or two short sentences of plain speech: no markdown, no "
            "lists, no emoji, no entity ids."
        )
        parts.append(VOICE_BRIEF_ANSWER_SHAPE)
        parts.append(VOICE_BRIEF_NO_INFERRED_EVENTS)
        parts.append(VOICE_BRIEF_PINNED_FACTS)
        # DAV-33. Until now this block existed in const.py but was never wired in,
        # so the shipped brief was the arm that regressed P06/P10/P13/P19 — four
        # present-tense sentences where Jarvis asserted a reading does not exist
        # while sensor.house_power_draw_from_inverter sat at 1681 W. Pinning the
        # entities recovers all four AND is faster (P19: wrong at 8.3 s -> right at
        # 4.0 s), because it replaces a search with a lookup. It is wired in here
        # rather than left in the harness because the thing I measure has to be the
        # thing that ships; that gap is exactly what made Arm 3 unreproducible.
        parts.append(VOICE_BRIEF_PINNED_POWER)
        # DAV-33, 19 Oct. Wired in in the same commit that defines it, because the
        # last time a VOICE_BRIEF_* block sat in const.py un-appended the harness
        # and the house sent different briefs for three days. The drift guard in
        # tests/test_voice_brief.py reads this append order out of the source, so
        # adding the constant without adding the line here fails the tests.
        parts.append(VOICE_BRIEF_PINNED_EVENTS)
        # DAV-36. Wired in in the same commit that defines it, for the reason above.
        # Last of the five because it is the narrowest: it corrects one reading that
        # the other four would otherwise let through, rather than telling Jarvis
        # where to look.
        parts.append(VOICE_BRIEF_PINNED_NAMES)
        if user_input.extra_system_prompt:
            parts.append(user_input.extra_system_prompt)
        return " ".join(parts)

    async def _async_fallback(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
        cause: str,
        detail: str,
    ) -> conversation.ConversationResult:
        """Keep voice alive when Jarvis does not answer.

        The local-intent retry below cannot help a sentence that arrived from the
        preferred pipeline: that pipeline already ran the same matcher and only
        reached this entity because it returned None (assist_pipeline/pipeline.py,
        `prefer_local_intents`). It is kept because it costs nothing and it is the
        only local attempt on every other route in — see DEFAULT_FALLBACK_LOCAL.
        So the spoken sentence, not this retry, is what ~19 voice turns in 20
        currently come down to. It is worth getting the words right.
        """
        _LOGGER.warning("Jarvis did not answer (%s: %s); falling back", cause, detail)

        if self._option(CONF_FALLBACK_LOCAL, DEFAULT_FALLBACK_LOCAL):
            local = await conversation.async_handle_intents(
                self.hass, user_input, chat_log
            )
            if local is not None:
                speech = local.speech.get("plain", {}).get("speech", "")
                chat_log.async_add_assistant_content_without_tools(
                    conversation.AssistantContent(
                        agent_id=conversation.HOME_ASSISTANT_AGENT, content=speech
                    )
                )
                return conversation.ConversationResult(
                    response=local, conversation_id=chat_log.conversation_id
                )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_error(
            intent.IntentResponseErrorCode.UNKNOWN,
            FALLBACK_SPEECH.get(cause, FALLBACK_SPEECH[ERR_UNREACHABLE]),
        )
        return conversation.ConversationResult(
            response=response, conversation_id=chat_log.conversation_id
        )
