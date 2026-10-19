#!/usr/bin/env python3
"""DAV-33 checks for the voice brief. Plain `python3 test_voice_brief.py`.

No pytest, no Home Assistant, no network, no Jarvis call — so this costs
nothing and can run on every change, which is the point: the Arm 2/Arm 3 brief
that produced DAV-29 Part B's accuracy numbers was assembled in a throwaway
harness and is not recoverable, because a `system` message on
/v1/chat/completions becomes `ephemeral_system_prompt` and Hermes never caches
that. These assertions are what stops the same thing happening to this one.

They are deliberately about CONTENT, not wording. Asserting the exact prose
would make every edit a test failure and teach the next person to update the
expectation without reading it. Asserting "the refusal rule is present, the
three entity ids are present, and nothing contradicts them" keeps failing for
the reason you want it to fail.
"""

import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "jarvis_conversation"

spec = importlib.util.spec_from_file_location("const", ROOT / "const.py")
const = importlib.util.module_from_spec(spec)
spec.loader.exec_module(const)

FAILS = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILS.append(name)


def render_room_unknown(language="en"):
    """Reproduce _system_prompt's room-unknown branch without Home Assistant.

    Mirrors conversation.py::_system_prompt. The branch matters: a probe
    harness has no device_id, so this is the exact string the measurement
    sends, and the one the DAV-33 numbers will be quoted against.
    """
    return " ".join([
        "This request arrived through Home Assistant Assist and your reply will be "
        "read aloud by a speaker.",
        "The room is unknown. If the request depends on which room it came from, "
        "ask which room rather than guessing.",
        f"Spoken language: {language}.",
        "Answer in one or two short sentences of plain speech: no markdown, no "
        "lists, no emoji, no entity ids.",
        const.VOICE_BRIEF_ANSWER_SHAPE,
        const.VOICE_BRIEF_NO_INFERRED_EVENTS,
        const.VOICE_BRIEF_PINNED_FACTS,
        const.VOICE_BRIEF_PINNED_POWER,
    ])


brief = render_room_unknown()

print("\nthe refusal rule (DAV-33 §1.1)")
rule = const.VOICE_BRIEF_NO_INFERRED_EVENTS.lower()
# It must generalise. If it names the washing machine it has memorised the one
# sentence we happened to catch, which is the failure mode the ticket called out
# by name — so the appliance being ABSENT is the assertion.
check("does not name the washing machine", "washing" not in rule,
      "the rule must generalise, not memorise the sentence we found")
check("does not name any single appliance",
      not any(w in rule for w in ("dishwasher", "kettle", "tumble", "oven", "boiler")))
# The trigger is the grammar of the question, so several past-tense shapes have
# to be recognisable in it — not just "did ... finish".
for shape in ("did it finish", "has it been opened", "when did it last run",
              "what has been going on today", "was anything unusual"):
    check(f"covers the shape {shape!r}", shape in rule)
check("names the resting-state error", "resting state" in rule)
check("says a refusal is a correct answer",
      "cannot tell is a correct answer" in rule)
# The carve-out has to survive, or the rule refuses questions it can answer.
check("allows a stored value that records the event",
      "stored value that records that event" in rule)
# DAV-33, 19 Oct. The hardening the owner chose. These four assertions exist
# because the rule ALREADY forbade this in a Python comment and the model did it
# anyway: "its state machine last changed at ten thirty-six this morning, which
# suggests it finished a cycle then". A rule in a comment is not a rule.
check("names last_changed as forbidden evidence", "last_changed" in rule)
check("names last_updated too", "last_updated" in rule)
check("gives the restart reason, not just the prohibition",
      "restart" in rule and "restore" in rule,
      "naming WHY the timestamp lies is what makes it stick")
check("forbids reasoning from a bare last-changed time",
      "only thing you have is when a state last changed" in rule)

print("\nthe three pinned facts (DAV-33 §1.2)")
facts = const.VOICE_BRIEF_PINNED_FACTS
for entity in ("sensor.solar_inverter_state_of_charge",
               "sensor.hottest_temprature",
               "sensor.coldest_temprature",
               "_radiator_local_temperature"):
    check(f"pins {entity}", entity in facts)
check('names the battery friendly name "House Charge"', "House Charge" in facts)
# The owner's own spelling. A well-meaning "fix" here silently breaks the fact,
# because the entity id really is spelled this way in his install.
check("keeps the owner's spelling of temprature",
      "temperature" not in facts.split("_radiator_local_temperature")[0]
      or "hottest_temprature" in facts)
# DAV-32's outage ended at 10:35:44 UTC on 16 Oct, two hours before this shipped.
# A pinned fact Jarvis cannot re-check must not assert a transient condition.
check("does not pin the Downstairs Bathroom outage as a standing fact",
      "unavailable" not in facts.lower() and "dead" not in facts.lower(),
      "the sensor recovered on 16 Oct; see the comment above the constant")

print("\nthe assembled brief")
check("brief is assembled in the documented order",
      brief.index(const.VOICE_BRIEF_ANSWER_SHAPE)
      < brief.index(const.VOICE_BRIEF_NO_INFERRED_EVENTS)
      < brief.index(const.VOICE_BRIEF_PINNED_FACTS)
      < brief.index(const.VOICE_BRIEF_PINNED_POWER))
# THE DRIFT GUARD. render_room_unknown() above is a COPY of the assembly in
# conversation.py, and on 19 Oct the copy lied: VOICE_BRIEF_PINNED_POWER had been
# in const.py since 16 Oct, was in the probe harness, and was never wired into the
# adapter — so "the brief" in the tests and "the brief" on the voice path were two
# different strings for three days. Rather than trust a third hand-kept copy, read
# the real order out of conversation.py's source and insist they match.
_src = (pathlib.Path(__file__).resolve().parents[1]
        / "custom_components" / "jarvis_conversation" / "conversation.py").read_text()
_shipped = re.findall(r"parts\.append\((VOICE_BRIEF_[A-Z_]+)\)", _src)
_tested = ["VOICE_BRIEF_ANSWER_SHAPE", "VOICE_BRIEF_NO_INFERRED_EVENTS",
           "VOICE_BRIEF_PINNED_FACTS", "VOICE_BRIEF_PINNED_POWER"]
check("the tested brief is the brief conversation.py actually sends",
      _shipped == _tested, f"conversation.py appends {_shipped}, tests render {_tested}")
# Standing context on a latency-critical path. At DAV-29's measured 14.2 ms per
# 1,000 prompt tokens this is single-digit milliseconds, but the real risk is
# drift: the moment this grows into a knowledge base it is the 75 KB skill file
# again, which is the thing the voice profile exists to remove.
check("brief stays small", len(brief) < 4000, f"{len(brief)} chars")
check("no markdown leaked into a spoken-context prompt",
      not any(m in brief for m in ("```", "\n- ", "**")))

print("\nthe reasoning toggle")
check("reasoning effort is off by default", const.DEFAULT_REASONING_EFFORT == "none")

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
