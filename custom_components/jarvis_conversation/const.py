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
#
# HARDENED 2026-10-19, and this is the owner's decision, not a tidy-up. The
# 14:46 probe on 16 Oct added VOICE_BRIEF_PINNED_POWER and the longer brief
# walked straight into the trap the paragraph above only described in a COMMENT:
#   "its state machine last changed at ten thirty-six this morning, WHICH
#    SUGGESTS IT FINISHED A CYCLE THEN"
# The machine had not run since 10 Oct; 10:36 was Home Assistant restarting and
# restoring the helper, exactly as Friday predicted in writing on DAV-35 at
# 12:13 before I ran it. A rule that lives in a comment is not a rule, so
# `last_changed`/`last_updated` and the restore-on-restart reason are now named
# in the brief text itself. The owner chose this over applying as-is, dropping
# `reasoning_effort: none`, or stopping (DAV-33 interaction adc474da, question
# `next-step` -> `harden-and-remeasure`, resolved 2026-10-16 14:45:41 UTC,
# `human_only`). It is the ONLY change in this commit: the four present-tense
# recoveries from VOICE_BRIEF_PINNED_POWER are deliberately left exactly as they
# were, so the re-measurement varies one thing.
VOICE_BRIEF_NO_INFERRED_EVENTS: Final = (
    "You can see what the house is right now; you cannot see what it did earlier. "
    "If the question is about something that happened rather than something that is "
    "true now — did it finish, has it been opened, when did it last run, what has "
    "been going on today, was anything unusual — then answer it only from a stored "
    "value that records that event itself, such as a sensor whose own name says it "
    "holds a last-run or a daily total. Otherwise say plainly that you cannot tell "
    "from here. A device that is idle, off, closed or at rest tells you nothing "
    "about whether it ran: never turn a resting state into a finished event, and "
    "never offer a guess about the past as though it were a reading. "
    "One trap in particular: how long ago a value last changed is not a record of "
    "what happened. Never treat an entity's last_changed or last_updated time — or "
    "any phrase like \"it last changed at\" — as evidence that something ran, "
    "started or finished. It marks only when the state last moved, and Home "
    "Assistant restores its helpers and switches when it restarts, so that "
    "timestamp is very often the restart itself rather than anything the house "
    "did. If the only thing you have is when a state last changed, you cannot "
    "tell, and you must say so rather than reasoning from it. "
    "Saying you cannot tell is a correct answer; guessing is not."
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
#
# PIN SEVEN REWRITTEN 2026-10-19, and this is the owner's decision: DAV-33
# interaction 23d836dd, question `next-step` -> `fix-pin-and-remeasure`,
# resolved 2026-10-19 08:55:19 UTC, `human_only`. It is the ONLY change in this
# commit. P18's wording was offered as a separate option on the same card and
# was NOT chosen, so it is deliberately untouched and the re-measurement again
# varies one thing.
#
# THE DEFECT. The old line said "the binary sensors ending _battery_plus_low
# that are on are the answer". `[measured]` 2026-10-19 09:4x UTC against live
# HA state, 6,047 entities: there are THREE sibling families, not one --
#   _battery_plus_low     46 entities, 41 off / 5 unavailable, ZERO on
#   _battery_plus_low_2   28 entities, 24 off / 4 ON
#   _battery_low          15 entities, 13 off / 2 unavailable, ZERO on
# Every live flag in this house is in the `_2` family, which the old line's
# suffix excludes. So the pin as written points at a set that is always empty,
# and a Jarvis that obeyed it literally would say "nothing is low" while five
# devices sit at 0-2 %.
#
# A CORRECTION TO MY OWN 08:24 REPORT, which said "of the 46 _battery_plus_low
# binary sensors, zero are on, so 'flagged' is wrong". The first half is true
# and the conclusion drawn from it is not: I filtered on `_battery_plus_low`
# and never saw `_battery_plus_low_2`. The four devices Jarvis named really
# ARE flagged -- `[measured]` all four read `on` continuously from before
# 06:00, i.e. during the 08:08 run -- and "flagged" is the right word in a
# house whose `automation.low_battery_notifications_actions` is driven off
# exactly these. P13 is still a partial, but for the narrower reason that it
# invented a fifth device: `[measured]` En-Suit Presence is at 50 % and its
# flag is off. The pin was wrong either way; my description of how was.
#
# WHY THE NEW LINE NAMES A TOOL CALL RATHER THAN A SUFFIX. `[measured]` from
# ~/.hermes/plugins/homeassistant/tools.py:93-120 on the live LXC,
# `ha_list_entities` returns only entity_id / state / friendly_name -- it does
# NOT expose device_class, so "the battery binary sensors" is not a filter
# Jarvis can actually run. Its `area` argument is really a substring match
# against friendly_name, so area="battery" is the one call that reaches all of
# them: 89 entities, exactly the 4 that are on, ~10 KB of payload. Going by
# state rather than by suffix is what makes this robust to the `_2` churn that
# broke the old line, and is why the suffixes are documented here and kept OUT
# of the brief -- the brief is standing context on a latency-critical path.
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
    "Seven: for what is low on battery, list binary_sensor with the area filter "
    '"battery": that one call returns every battery flag in the house, and the '
    "ones reading on are the answer. Do not go by entity-id suffix, they vary. "
    "Name only the ones that came back on; if none is on, say nothing is "
    "flagged low. "
    "If one of these is genuinely missing or unavailable, say so; do not say the "
    "house has no such reading when you simply have not found it."
)

# DAV-33: a THIRD pinned block, again kept separate so it can be judged -- or
# dropped -- on its own. It is the owner's decision: DAV-33 interaction
# 0f523bbb, question `next-step` -> `pin-event-helpers`, resolved 2026-10-19
# 09:19:19 UTC, `human_only`. It is the ONLY change in this commit.
#
# THE FAULT IT FIXES. The 19 Oct 10:05 run left exactly one failure standing,
# and it was the last thing between this profile and the bar. P09 "did the
# washing machine finish" refused -- which the rule permits -- but justified
# the refusal with a claim about the house:
#     "there's no last-run or finished sensor"
# P14 did the identical thing with the heating: "no record of the last time it
# came on". `[measured]` 2026-10-19 09:22 UTC against live HA state, both
# records exist and hold real values:
#     input_datetime.washing_machine_last_finished = 2026-10-17 12:11:40
#     input_datetime.heating_last_on               = 2026-10-19 06:32:00
# and C1 and C5, in the SAME run, read those very entities and answered
# correctly. So the refusal was in the safe direction but was still a spoken
# falsehood, which is the same fault I failed P18 for on 16 Oct.
#
# WHY IT HAPPENED, which is mechanical and not a mood. `[measured]` from the
# recorded tool calls in state.db, replayed against live state:
#     P09  ha_list_entities(domain="sensor",        area="washing")  ->   4   no helper
#          ha_list_entities(domain="binary_sensor", area="washing")  ->   0   no helper
#          ha_list_entities(domain="switch",        area="washing")  ->   2   no helper
#          ha_list_entities(                        area="utility")  ->   0   no helper
#     C1   ha_list_entities(                        area="washing")  ->  20   HELPER, first row
#     P14  ha_list_entities(domain="sensor",        area="heating")  ->  50   no helper
#          ha_list_entities(domain="climate")                        ->  20   no helper
#     C5   ha_list_entities(                        area="heating")  -> 124   HELPER
# Every failing call carried a DOMAIN FILTER, and the records are
# `input_datetime` helpers -- a domain Jarvis never tried, because a stored
# reading sounds like a sensor. The filter excluded the answer and Jarvis then
# reported its own empty result as a fact about the house. "There is no
# last-run sensor" is true of `domain=sensor` and false of this house.
#
# That is the same shape as pin seven's defect -- a filter that cannot return
# the answers -- which is why the fix is the same one that worked: name the
# entity, and say what it is, so the lookup replaces the search.
#
# WHAT I DELIBERATELY DID NOT WRITE. The general rule ("event records in this
# house are helpers, so never filter by domain when hunting for one") would
# probably fix more than two sentences. It is also a broader change than the
# one authorised, and generalising beyond the evidence is what cost me the
# 16 Oct run. Two entities, named, measured, and nothing else. Also left
# untouched: VOICE_BRIEF_NO_INFERRED_EVENTS still says the carve-out is "a
# SENSOR whose own name says it holds a last-run", and that wording may itself
# be steering the domain filter. Flagged in the report, not changed here,
# because the re-measurement has to vary one thing.
#
# PIN TEN ADDED 2026-10-19, and it exists to repair damage this very block did.
# It is the owner's decision: DAV-33 interaction f59def8a, question `next-step`
# -> `fix-n2-first`, resolved 2026-10-19 09:41:02 UTC, `human_only`. It is the
# ONLY change in this commit.
#
# THE REGRESSION. Pins eight and nine fixed P09 and P14 and took N2 with them,
# in the wrong direction. N2 "how many times has the boiler come on today" was
# RIGHT on the 10:05 run -- "Once so far today, the boiler cycle counter stands
# at one" -- and on the 10:30 run it became:
#     "I can tell you the heating last came on at half past six this morning,
#      but not how many times it has run today — THE HOUSE KEEPS NO COUNT OF
#      THAT."
# `[measured]` 2026-10-19 10:4x UTC against live HA state: counter
# .boiler_daily_cycles = 1, friendly name "Boiler Daily Cycles", reset nightly
# by automation.boiler_reset_cycle_counter_daily, and switch.heating_boiler has
# exactly one off->on edge today. The count was there and the sentence denied
# it existed -- the same spoken-falsehood class pins eight and nine were added
# to stop, which makes it mine rather than variance.
#
# WHY IT HAPPENED, which is the pin working too well. Pin nine named one entity
# for "the heating" and replaced a search with a lookup; that is the whole
# mechanism and it is why P14 went from three tool calls to one. N2 is also
# about the heating, so it took the same lookup -- `[measured]` tool_call_count
# = 1 on that probe -- read a timestamp, found it could not answer a how-many
# question from it, and stopped. Before pin nine it had no shortcut and
# searched until it found the counter. So a pin does not merely add an answer:
# it OUTCOMPETES the search for every sentence that looks adjacent to it, and
# anything the pinned entity cannot answer has to be pinned too or it is lost.
# That is a general cost of this technique and it belongs in the report.
#
# THE FIX IS THE SAME ONE THAT WORKED, PLUS A BOUNDARY. Naming the counter is
# pins four to nine over again. The second sentence is the new part and is the
# half that is really about the regression: it tells Jarvis what pin nine
# cannot do, so the lookup hands the question on instead of ending it. I have
# deliberately NOT written the general rule ("when a pinned entity cannot
# answer, keep looking") -- it would probably help more sentences and it is a
# broader change than the one authorised, and generalising beyond the evidence
# is what cost me the 16 Oct run.
#
# WHAT I CONSIDERED AND DID NOT DO: rewording pin nine itself to narrow it. It
# is one line smaller, but it changes a line that is currently MEASURED GOOD --
# P14 and C5 both passed on it this morning -- to fix a sentence it was not
# aimed at. Adding beside it leaves the passing line alone.
VOICE_BRIEF_PINNED_EVENTS: Final = (
    "Three more, about what this house records for itself. The first two are "
    "input_datetime helpers rather than sensors, so a search narrowed to the "
    "sensor domain will not return them — read them by name. "
    "Eight: input_datetime.washing_machine_last_finished is when the washing "
    "machine last finished a cycle. "
    "Nine: input_datetime.heating_last_on is when the heating last came on. "
    "Ten: counter.boiler_daily_cycles is how many times the boiler has come on "
    "today, and it resets at midnight. Nine holds only the latest time and "
    "cannot answer a how-many question — read the counter for that. "
    "Each records the event itself, so reading one is a reading and not a "
    "guess. If one is unavailable say so, but never say the house keeps no "
    "record when you have not found it."
)
