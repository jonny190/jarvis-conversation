# Jarvis Conversation

A Home Assistant conversation agent that forwards a spoken sentence to the
household Jarvis gateway (an OpenAI-compatible `/v1/chat/completions` endpoint)
and speaks the reply.

It is deliberately thin. It owns three things Home Assistant does not give you
for free on this path: a **hard timeout**, a **fallback**, and **spoken-text
cleanup** before the reply reaches a per-character TTS provider.

## Install (HACS)

1. HACS → three-dot menu → **Custom repositories**
2. Repository: `jonny190/jarvis-conversation`, Category: **Integration**
3. Install, then **restart Home Assistant** — a full restart. "Quick reload"
   does not pick up a new custom component.
4. Settings → Devices & Services → **Add Integration** → *Jarvis Conversation*

After step 3 the integration is installed but **not configured**: it loads
nothing, calls nothing and costs nothing until you complete step 4.

## Configuration

Three fields in the config flow:

| Field | Meaning |
| --- | --- |
| URL | Base URL of the Jarvis gateway, e.g. `http://<host>:8642` |
| API key | Sent as `Authorization: Bearer <key>` |
| Model | Gateway model id, e.g. `hermes-agent` |

The key is stored in the Home Assistant config entry. **It is not in this
repository and must never be committed here.**

Validation uses `GET /v1/models`, which starts no agent turn.

Options (reconfigurable without a restart): request timeout (default 12 s),
whether to prefer Home Assistant's local intents, and spoken-text cleanup.

## What this does not fix

Two limits are properties of the agent behind the adapter, not of the adapter.
They are documented here because the right place to learn them is not a kitchen.

**Latency.** Measured over 20 sentences drawn from the population this adapter
actually routes (local matcher first, Jarvis only on a miss): median **27.7 s**,
p90 58.2 s, and **1 of 20 inside the 12 s default timeout**. Raising the timeout
trades a fast failure for a slow one. Most Jarvis-routed turns will hit the
timeout path.

**Cancellation is bounded, not absolute.** The adapter requests the gateway's
streaming path so that hanging up is *noticed*: the SSE writer sees the
disconnect and interrupts the turn, and a 10 s keepalive means it notices even
while the agent is silent mid-tool-call. Worst case detection is about one
keepalive interval. But:

- the interrupt is **cooperative** — Jarvis stops at its next checkpoint;
- a **tool call already dispatched is not recalled**. If the service call that
  turns a light on has gone out, stopping the loop that issued it does not
  undo it.

So a command can still land after Home Assistant has given up and spoken the
timeout line. The spoken line says so.

Nothing is streamed to the speaker — the reply is still collected whole before
it is spoken. The streaming request exists only so that a hangup means
something.

## Rollback

- **Pipeline:** set the pipeline's conversation agent back to `Home Assistant`.
  One field, no restart. This is the fast rollback and it is the one to reach
  for first.
- **Entry:** delete the config entry. Removes `conversation.jarvis`.
- **Component:** uninstall in HACS, then restart Home Assistant.

## Tests

`python3 tests/test_speech.py` and `python3 tests/test_stream.py`. Both run on
plain Python — no Home Assistant, no pytest, no network, and no Jarvis call.
