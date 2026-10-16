"""Constants for the Jarvis Conversation integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "jarvis_conversation"

CONF_URL: Final = "url"
CONF_API_KEY: Final = "api_key"
CONF_MODEL: Final = "model"
CONF_TIMEOUT: Final = "timeout"
CONF_FALLBACK_LOCAL: Final = "fallback_local"
CONF_MAX_SPOKEN_CHARS: Final = "max_spoken_chars"

# Deliberately empty. This value only pre-fills the URL box in the config flow, but
# this repository is public, so a real address here would publish the gateway's host
# and port. Type the URL at install time instead.
DEFAULT_URL: Final = ""
DEFAULT_MODEL: Final = "hermes-agent"

# Hard ceiling on a single voice turn. The Assist pipeline puts NO timeout around
# conversation.async_converse() in 2026.9.0, and assist_satellite calls
# async_pipeline_from_audio_stream(), whose signature has no timeout at all — so this
# value is the only thing standing between a slow Jarvis and a wedged voice pipeline.
#
# This is a SAFETY CEILING, not a latency Jarvis usually meets. Read on an earlier
# version of this comment it looked like the latter, because it quoted the 5.5 s
# DAV-24 route probe — one sample, and the easiest sentence in the space.
#
# Measured against the traffic this entity actually receives (DAV-25, n = 20 read-only
# voice sentences that HA's local matcher had already failed, so they route here):
#
#     min 6.5 s | p50 27.7 s | p90 58.2 s | max 129.3 s
#     inside 12 s:  1 / 20      inside 30 s: 11 / 20      inside 60 s: 18 / 20
#
# So at 12 s roughly 19 turns in 20 end in the spoken fallback below. Raising this is
# a one-field change in the integration's options (2–60 s) and needs no redeploy; it
# buys answered turns at the price of the user standing there waiting for them. The
# household owns that trade-off, so the default stays at the safe end.
#
# What this timeout does to Jarvis changed in 0.1.2, so the old one-liner here
# ("stops us waiting; does not cancel Jarvis") is no longer the whole story.
#
# Giving up now closes the response stream, and the gateway's SSE writer treats a
# closed stream as a reason to interrupt the turn and reap its background processes.
# It notices on its next write, which its own 10 s keepalive guarantees happens even
# while the agent is silent. Measured on the gateway's aiohttp (3.14.3), hangup at
# 12 s: on the old buffered path the server never found out and the turn ran to
# completion; on the streaming path it was detected at 20 s.
#
# So the overhang is bounded now, not gone. Two gaps survive and the ERR_TIMEOUT
# wording in conversation.py still has to cover them:
#   - the interrupt is cooperative, so Jarvis stops at its next checkpoint;
#   - a tool call already issued is not recalled by stopping the loop that issued
#     it, so the DAV-25 driveway light could still come on — just sooner, and
#     without the rest of the turn running behind it.
DEFAULT_TIMEOUT: Final = 12.0

# When Jarvis times out or errors, retry the sentence against Home Assistant's own
# local intent matcher before giving up.
#
# Be precise about what this can and cannot do. Sentences arriving from the preferred
# pipeline have ALREADY been through this same matcher: with prefer_local_intents
# enabled, assist_pipeline/pipeline.py calls conversation.async_handle_intents() and
# only falls through to this entity when it returns None. Retrying it here cannot
# succeed on that traffic — verified in source and measured (DAV-25: 0 of 20).
#
# It is still worth keeping, because it is free and it is the only local attempt on
# every other path into this entity: a direct conversation.process service call, a
# pipeline with prefer_local_intents off, or this entity being given CONTROL later
# (which narrows the pipeline's local pass to GET_STATE and MEDIA_SEARCH_AND_PLAY and
# leaves everything else to this fallback).
DEFAULT_FALLBACK_LOCAL: Final = True

# Ceiling on the characters handed to text-to-speech in one turn. ElevenLabs bills per
# character, so an answer that ignores the "one or two short sentences" instruction in
# the system prompt costs real money to read out. Two short sentences run ~150
# characters; 500 leaves generous headroom and still bounds the bill. Set to 0 to
# disable the cap. Cutting prefers the last sentence boundary before the limit.
DEFAULT_MAX_SPOKEN_CHARS: Final = 500

# Marks the Hermes session so turns from one HA conversation share long-term memory.
SESSION_ID_PREFIX: Final = "ha-assist-"

# Reasoning effort asked for on every voice turn.
#
# DAV-29 Part A measured 53 % of every output token Jarvis produced on this route to
# be `reasoning_content` that nobody hears — ~7 seconds of silence in a 27.7 s turn.
# Hermes accepts per-request reasoning config on /v1/chat/completions
# (`api_server.py:333`, reached at `api_server_openai_routes.py:725`), so this is
# scoped to the voice route by construction: WhatsApp, Telegram, CLI and cron are
# untouched because they never send it.
#
# `[measured]` DAV-29 Part B: reasoning_tokens went to zero in both arms that set
# this, confirming the toggle is honoured by deepseek-v4-flash and not merely
# advertised in the catalogue.
#
# Set to None to send no `model_options` at all and let the gateway default apply.
DEFAULT_REASONING_EFFORT: Final[str | None] = "none"

# The voice brief — the client half of the voice profile.
#
# WHY THIS IS A NAMED CONSTANT AND NOT AN f-STRING BURIED IN _system_prompt.
# The Arm 2/Arm 3 brief that produced DAV-29 Part B's numbers was assembled inside a
# throwaway harness and is NOT recoverable: Hermes stores the standing system prompt
# in `system_prompts` keyed by hash, but a `system` message on /v1/chat/completions
# becomes `ephemeral_system_prompt`, which `agent/system_prompt.py:766` injects at
# API-call time and never caches. So the exact wording behind "9 right, 5 partial,
# 3 wrong" is gone. That is a measurement I cannot reproduce byte-for-byte, and the
# fix is for the brief to live in version control from now on.
#
# Sent as the `system` message. Per DAV-29 §4.3 this is ADDITIVE — it is appended to
# Jarvis's standing prompt, it does not replace it.

# Layer 1a — the shape of a spoken answer, and the instruction not to script.
#
# "Do not write or run scripts" is necessary but NOT sufficient, and DAV-29 Part B
# proved it the expensive way: Arm 2 had this text and every file tool still in hand,
# and simply swapped Python for 36 `search_files` calls — ending up slower AND less
# accurate (7 wrong) than Arm 3, which had the same text and no file tools. Telling
# it not to use them makes it worse; taking them away works. So this paragraph only
# pays off alongside `platform_toolsets.api_server: [homeassistant]` on the gateway.
VOICE_BRIEF_ANSWER_SHAPE: Final = (
    "This is a spoken turn, so answer it the way a person in the room would: one "
    "short sentence, two at the very most. Read what you need straight from Home "
    "Assistant with ha_get_state and ha_list_entities. Do not write a file, do not "
    "run a script and do not open a terminal to answer a question about the house — "
    "if it cannot be read from entity state, say so instead."
)

# Layer 1b — the refusal rule (DAV-33 §1.1).
#
# THE FAILURE THIS EXISTS TO STOP. DAV-29 Part B, Arm 3, "did the washing machine
# finish" -> "Yes, Sir — the cycle has finished." The machine was idle at 0 W and had
# not run at all that day. The baseline, which could reach the history API, said so
# correctly. Arm 3 saw a resting state and narrated a completed event.
#
# That is the worst shape of error a house assistant has: confident, spoken, wrong,
# and unverifiable by the person listening — they asked precisely because they could
# not see for themselves.
#
# Written to generalise rather than to memorise the washing machine. The trigger is
# the GRAMMAR OF THE QUESTION (did / has / when / what happened — the past), not a
# list of appliances, because the four ha_* tools cannot reach /api/history or
# /api/logbook at all, so EVERY past-tense question is outside this profile's
# competence, not just the one we happened to catch.
#
# The carve-out is deliberate and narrow: a stored value that records the event
# itself is a reading, not an inference. "Last run finished at 14:02" from an entity
# whose own name says it tracks that is fine. `last_changed` on an idle switch is
# not — it says when the state last moved, not what happened.
VOICE_BRIEF_NO_INFERRED_EVENTS: Final = (
    "You can see what the house is right now; you cannot see what it did earlier. "
    "If the question is about something that happened rather than something that is "
    "true now — did it finish, has it been opened, when did it last run, what has "
    "been going on today, was anything unusual — then answer it only from a stored "
    "value that records that event itself, such as a sensor whose own name says it "
    "holds a last-run or a daily total. Otherwise say plainly that you cannot tell "
    "from here. A device that is idle, off, closed or at rest tells you nothing "
    "about whether it ran: never turn a resting state into a finished event, and "
    "never offer a guess about the past as though it were a reading. Saying you "
    "cannot tell is a correct answer; guessing is not."
)

# Layer 1c — three pinned facts (DAV-33 §1.2).
#
# These replace the ~75 KB `home-assistant` SKILL.md, which goes away with the
# `skills` toolset (DAV-29 §4.2: dropping `skills` deletes the whole index via
# `system_prompt.py:301-305`). The skill file is why the full-capability Jarvis
# scored 20/20; this is the cheap half of what it was providing — the three specific
# things the trimmed profile measurably got wrong, and nothing else.
#
# Each line is here because Arm 3 failed it, not because it seemed useful:
#   - "how much battery have we got left" -> gave volts and gave up. The percentage
#     entity exists, is called "House Charge", and read 28 % at the time.
#   - "which room is the warmest" -> "the downstairs bathroom, about thirty-two
#     degrees", which is a TRV with a +10 °C calibration offset. The owner's own
#     helper read 26.3. Note the spelling of the two helper entities is the owner's
#     and is correct as written — do not "fix" it.
#   - the same TRV, generalised: a radiator valve reports the metal it is bolted to,
#     not the room.
#
# ON THE DOWNSTAIRS BATHROOM, AND WHY THIS LINE DOES NOT SAY WHAT DAV-33 ASKED IT TO.
# The ticket told me to pin "its real room sensor has been dead since 24 Sept
# (DAV-32)". `[measured]` 2026-10-16 12:52 UTC, from the live HA history API:
# `sensor.downstairs_bathroom_environment_temperature` came back at **10:35:44 UTC
# that same morning** and has reported continuously since (20.52 -> 24.1 °C over the
# following hour). DAV-32 is stale and I have said so on it. Pinning a dead-sensor
# claim would have shipped a fact that stopped being true two hours before I wrote
# it — and the whole point of this block is that Jarvis cannot check it.
#
# So the line keeps the half that is durably true and verifiable, and drops the half
# that was an outage. `[measured]` same read, the calibration numbers are real and
# not confined to one room: Downstairs Bathroom +10, En-Suit +10, Alex's Office +5,
# Bedroom +3.8, Office +2.8, Kitchen +1, Front Room 0, Livingroom -0.4, Main
# Bathroom -2.4. Downstairs Bathroom's TRV read 35.7 against the room's real 24.1 at
# the same instant. Naming the right entity to use instead is also strictly more
# useful than a prohibition on its own.
#
# Keep this list SHORT. Every line is standing context on a latency-critical path,
# and the moment it grows into a knowledge base it has become the skill file again.
VOICE_BRIEF_PINNED_FACTS: Final = (
    "Three things about this house that you will otherwise get wrong. "
    "One: the battery charge is sensor.solar_inverter_state_of_charge, shown as "
    '"House Charge", and it is a percentage — use it for how much battery is left, '
    "not the inverter voltage. "
    "Two: sensor.hottest_temprature and sensor.coldest_temprature are the "
    "household's own helpers, spelled exactly like that, and they are the right "
    "answer to which room is warmest or coldest — read them rather than comparing "
    "temperature sensors yourself. "
    "Three: any entity ending in _radiator_local_temperature is a radiator valve "
    "reporting its own body temperature, not the room's, and every one of them "
    "carries a calibration offset — Downstairs Bathroom and En-Suit are both set "
    "ten degrees high. Never give a _radiator_local_temperature reading as a room "
    "temperature; the room's own environment or temperature sensor is the answer."
)

# DAV-33: a SECOND pinned block, kept separate from the three above so it can be
# judged -- or dropped -- on its own.
#
# WHY IT EXISTS. The 16:46 run regressed four present-tense sentences (P06, P10,
# P13, P19) and the cause was isolated to `reasoning_effort: none`: with low
# effort Jarvis stops hunting and asserts the data is not there, when in every
# one of those four cases an entity plainly holds it. Removing the parameter
# recovers all four but costs 10-37 s a turn, which the 12 s voice ceiling
# cannot pay. So instead of buying the answer with reasoning time, this tells it
# where to look -- exactly the mechanism that already fixed the battery
# percentage and the warmest room.
VOICE_BRIEF_PINNED_POWER: Final = (
    "Four more, about power and the weather, where the entity names do not "
    "announce themselves and looking around for them is slow. "
    "Four: what the house is drawing right now is "
    "sensor.house_power_draw_from_inverter, in watts. "
    "Five: for grid versus battery, read sensor.solar_inverter_power_from_grid, "
    "sensor.solar_inverter_battery_discharge and "
    "sensor.solar_inverter_pv_power_array together — if the grid figure is zero "
    "the house is running on its own solar and battery. "
    "Six: the outdoor weather sensor is dead, so for the temperature outside use "
    "the weather.home entity's temperature attribute rather than hunting for an "
    "outdoor sensor. "
    "Seven: for what is low on battery, the binary sensors ending "
    "_battery_plus_low that are on are the answer — name them and count them "
    "carefully. "
    "If one of these is genuinely missing or unavailable, say so; do not say the "
    "house has no such reading when you simply have not found it."
)
