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

DEFAULT_URL: Final = "http://192.168.5.230:8642"
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
