#!/usr/bin/env python3
"""Checks for the 0.1.2 SSE reader. Plain `python3 test_stream.py`, no pytest,
no Home Assistant, no network, no Jarvis call.

Frames here are not invented: they are built the way
`gateway/platforms/api_server.py::_sse_frame` builds them
(`[id:][event:]data: <json>\\n\\n`) and carry the payloads
`_write_sse_chat_completion` actually writes — the opening role chunk, content
deltas, `reasoning_content` deltas, the `hermes.tool.progress` /
`hermes.status` custom events, the finish chunk with its optional `error`, and
`data: [DONE]`. The `: keepalive` comment is the one the idle branch of
`_iter_stream_items` writes every 10 s.
"""

import asyncio
import json
import sys
import types

# Import conversation.py without Home Assistant installed: stub only the symbols
# it imports at module scope. The functions under test touch none of them.
for name in (
    "homeassistant",
    "homeassistant.components",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity_platform",
    "aiohttp",
):
    sys.modules.setdefault(name, types.ModuleType(name))


class _Any:
    """Stands in for any attribute these stub modules are asked for."""

    def __getattr__(self, item):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()

    def __class_getitem__(cls, item):
        return _Any()


for name, attrs in {
    "homeassistant.components": ("conversation",),
    "homeassistant.config_entries": ("ConfigEntry",),
    "homeassistant.const": ("MATCH_ALL",),
    "homeassistant.core": ("HomeAssistant",),
    "homeassistant.helpers": ("area_registry", "device_registry", "intent"),
    "homeassistant.helpers.aiohttp_client": ("async_get_clientsession",),
    "homeassistant.helpers.device_registry": ("DeviceEntryType", "DeviceInfo"),
    "homeassistant.helpers.entity_platform": ("AddConfigEntryEntitiesCallback",),
    "aiohttp": ("ClientError",),
}.items():
    for attr in attrs:
        setattr(sys.modules[name], attr, _Any())
sys.modules["aiohttp"].ClientError = type("ClientError", (Exception,), {})
# conversation.ConversationEntity must be a real base class to subclass.
sys.modules["homeassistant.components"].conversation = types.SimpleNamespace(
    ConversationEntity=type("ConversationEntity", (), {}),
    ConversationEntityFeature=lambda v: v,
)

import pathlib  # noqa: E402

# Register the package without running its __init__.py: that file wires up HA
# config entries and needs far more of Home Assistant than the SSE reader does.
# Relative imports inside conversation.py still resolve, via __path__.
_pkg = types.ModuleType("jarvis_conversation")
_pkg.__path__ = [str(pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "jarvis_conversation")]
sys.modules["jarvis_conversation"] = _pkg

from jarvis_conversation.conversation import _async_collect_stream  # noqa: E402

PASS = FAIL = 0


def check(label: str, got, want) -> None:
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


def frame(data, event=None) -> bytes:
    """Byte-for-byte what _sse_frame produces."""
    prefix = f"event: {event}\n" if event else ""
    return f"{prefix}data: {json.dumps(data)}\n\n".encode()


def chunk(delta, finish_reason=None, **extra) -> dict:
    """Byte-for-byte what the handler's local _chunk() produces."""
    return {
        "id": "chatcmpl-abc",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "hermes-agent",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        **extra,
    }


class FakeResponse:
    """Feeds bytes to `async for raw in resp.content` the way aiohttp does:
    one chunk per line, newline retained."""

    def __init__(self, blob: bytes):
        self._lines = blob.splitlines(keepends=True)

    @property
    def content(self):
        async def gen():
            for line in self._lines:
                yield line

        return gen()


def run(blob: bytes):
    return asyncio.run(_async_collect_stream(FakeResponse(blob)))


print("A normal turn")
blob = (
    frame(chunk({"role": "assistant"}))
    + frame(chunk({"content": "The kitchen light "}))
    + frame(chunk({"content": "is on."}))
    + frame(chunk({}, "stop", usage={"total_tokens": 10}))
    + b"data: [DONE]\n\n"
)
check("text is the concatenated deltas", run(blob)[0], "The kitchen light is on.")
check("finish_reason", run(blob)[1], "stop")
check("no error", run(blob)[2], None)

print("Keepalives, the frames that make a hangup detectable")
blob = (
    frame(chunk({"role": "assistant"}))
    + b": keepalive\n\n"
    + b": keepalive\n\n"
    + frame(chunk({"content": "Done."}))
    + b": keepalive\n\n"
    + frame(chunk({}, "stop"))
    + b"data: [DONE]\n\n"
)
check("keepalive comments are not spoken", run(blob)[0], "Done.")

print("reasoning_content must never reach the speaker")
blob = (
    frame(chunk({"role": "assistant"}))
    + frame(chunk({"reasoning_content": "Let me check the light registry first..."}))
    + frame(chunk({"content": "It's on."}))
    + frame(chunk({"reasoning_content": "...and that is the answer."}))
    + frame(chunk({}, "stop"))
    + b"data: [DONE]\n\n"
)
check("only content is collected", run(blob)[0], "It's on.")

print("Custom events on the same stream")
blob = (
    frame(chunk({"role": "assistant"}))
    + frame(
        {"tool": "hass_turn_on", "emoji": "x", "label": "hass_turn_on(light.kitchen)",
         "toolCallId": "c1", "status": "running"},
        event="hermes.tool.progress",
    )
    + frame({"state": "thinking"}, event="hermes.status")
    + frame({"question": "Run `rm -rf /`?", "choices": ["yes", "no"]},
            event="approval.request")
    + frame(chunk({"content": "Switched it on."}))
    + frame(chunk({}, "stop"))
    + b"data: [DONE]\n\n"
)
check("tool/status/approval events are not spoken", run(blob)[0], "Switched it on.")

print("A turn that ends badly")
blob = (
    frame(chunk({"role": "assistant"}))
    + frame(
        chunk(
            {},
            "error",
            error={"message": "provider refused the request", "type": "AgentError"},
            hermes={"completed": False, "partial": False, "failed": True},
        )
    )
    + b"data: [DONE]\n\n"
)
text, reason, err = run(blob)
check("no text", text, "")
check("finish_reason surfaces", reason, "error")
check("error message surfaces", err, "provider refused the request")

print("A partial turn still speaks what it got")
blob = (
    frame(chunk({"role": "assistant"}))
    + frame(chunk({"content": "The answer is "}))
    + frame(chunk({}, "length", hermes={"completed": False, "partial": True}))
    + b"data: [DONE]\n\n"
)
check("partial text kept", run(blob)[0], "The answer is ")
check("length finish_reason", run(blob)[1], "length")

print("Truncation: the stream just stops (what a crashed gateway looks like)")
blob = frame(chunk({"role": "assistant"})) + frame(chunk({"content": "Half a sen"}))
check("what arrived is returned", run(blob)[0], "Half a sen")
check("no finish_reason", run(blob)[1], None)

print("Malformed frames are skipped, not fatal")
blob = (
    frame(chunk({"role": "assistant"}))
    + b"data: {not json at all\n\n"
    + b"data: null\n\n"
    + b'data: ["a list, not an object"]\n\n'
    + frame({"object": "chat.completion.chunk", "choices": []})
    + frame({"object": "chat.completion.chunk", "choices": [None]})
    + frame({"object": "chat.completion.chunk", "choices": [{"delta": None}]})
    + frame(chunk({"content": "Still fine."}))
    + frame(chunk({}, "stop"))
    + b"data: [DONE]\n\n"
)
check("survives junk", run(blob)[0], "Still fine.")

print("Nothing after [DONE] is read")
blob = (
    frame(chunk({"content": "Real answer."}))
    + b"data: [DONE]\n\n"
    + frame(chunk({"content": " trailing rubbish"}))
)
check("stops at [DONE]", run(blob)[0], "Real answer.")

print("CRLF line endings")
blob = (
    b"data: " + json.dumps(chunk({"content": "Works."})).encode() + b"\r\n\r\n"
    + b"data: [DONE]\r\n\r\n"
)
check("CRLF handled", run(blob)[0], "Works.")

print("Non-ASCII survives the round trip")
blob = frame(chunk({"content": "It's 21°C — café warm."})) + b"data: [DONE]\n\n"
check("unicode intact", run(blob)[0], "It's 21°C — café warm.")

print("An empty stream")
check("empty text", run(b"data: [DONE]\n\n")[0], "")
check("empty body", run(b"")[0], "")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
