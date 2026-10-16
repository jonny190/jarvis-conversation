#!/usr/bin/env python3
"""DAV-28 verification for jarvis_conversation/speech.py.

Runs without Home Assistant or pytest: speech.py imports only the vendored
normalizer, which is pure stdlib. Every case is an assertion about what a
speaker would say and therefore about what ElevenLabs would bill for.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "jarvis_conversation"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# speech.py does `from .tts_text_normalize import ...`; load it as a package member.
pkg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("jarvis_conversation", loader=None, is_package=True)
)
pkg.__path__ = [str(ROOT)]
sys.modules["jarvis_conversation"] = pkg
spec = importlib.util.spec_from_file_location(
    "jarvis_conversation.speech", ROOT / "speech.py"
)
speech = importlib.util.module_from_spec(spec)
spec.loader.exec_module(speech)
prepare_for_tts = speech.prepare_for_tts

FAILS = []


def check(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        FAILS.append(f"{name}: {detail}")


# --- 1. The exact defect reported in DAV-28 ---------------------------------
# Quoted from the issue: a correct answer, then Hermes's turn-end footer.
LEAK = (
    "The heat pump is drawing about 1.2 kilowatts, the most of anything right now.\n\n"
    "⚠️ File-mutation verifier: 2 file edit(s) FAILED this turn despite any "
    "wording above that may suggest otherwise. Run `git status` or `read_file` to "
    "confirm what actually landed.\n"
    "  • `/home/hermes/.hermes/cache/scratch/power_now.py` — [write_file] "
    "Refusing to overwrite an existing file\n"
    "  • `/home/hermes/.hermes/cache/scratch/power2.py` — [write_file] "
    "Refusing to overwrite an existing file"
)
spoken = prepare_for_tts(LEAK, 500)
print("\nDAV-28 reproduction")
print(f"  raw content : {len(LEAK)} chars")
print(f"  spoken      : {len(spoken)} chars -> {spoken!r}")
check("answer survives", "heat pump" in spoken and "1.2 kilowatts" in spoken, spoken)
check("no verifier banner", "File-mutation" not in spoken, spoken)
check("no git status instruction", "git status" not in spoken, spoken)
check("no file paths", "hermes" not in spoken and ".py" not in spoken, spoken)
check("no tool names", "write_file" not in spoken, spoken)
check("no warning emoji", "⚠" not in spoken, spoken)
check("billed chars cut", len(spoken) < len(LEAK) / 3, f"{len(spoken)} vs {len(LEAK)}")

# --- 2. Reply that is nothing but the footer --------------------------------
print("\nFooter-only reply (must be treated as 'no answer', not spoken as '')")
only_footer = (
    "⚠️ File-mutation verifier: 1 file edit(s) FAILED this turn.\n"
    "  • `/tmp/x.py` — [write_file] Refusing to overwrite"
)
check("normalises to empty", prepare_for_tts(only_footer, 500) == "",
      repr(prepare_for_tts(only_footer, 500)))

# --- 3. Reasoning that leaks into content -----------------------------------
print("\n<think> block in content")
think = "<think>The user means the kitchen.</think>The kitchen light is on."
check("reasoning dropped", prepare_for_tts(think, 500) == "The kitchen light is on.",
      repr(prepare_for_tts(think, 500)))
unterminated = "The door is locked.\n<think>but I should check the back"
check("unterminated block dropped",
      "should check" not in prepare_for_tts(unterminated, 500),
      repr(prepare_for_tts(unterminated, 500)))

# --- 4. Ordinary answers must pass through intact ---------------------------
print("\nOrdinary answers are not mangled")
for plain in (
    "The front door is locked.",
    "Yes, the washing machine finished about ten minutes ago.",
    "It's 21 degrees in the lounge and 19 upstairs.",
):
    check(f"verbatim: {plain[:32]}...", prepare_for_tts(plain, 500) == plain,
          repr(prepare_for_tts(plain, 500)))

print("\nFormatting that costs money to speak")
md = "**Kitchen**: light is on.\n- Lamp: off\n- Fan: on \U0001f600"
out = prepare_for_tts(md, 500)
check("markdown and emoji removed",
      "**" not in out and "- " not in out and "\U0001f600" not in out, repr(out))
check("words kept", "Kitchen" in out and "Lamp" in out and "Fan" in out, repr(out))
temp = prepare_for_tts("It is 21°C outside.", 500)
check("units spoken as words", "degrees Celsius" in temp, repr(temp))

# --- 5. The character cap ----------------------------------------------------
print("\nCharacter cap (ElevenLabs bills per character)")
long_reply = ("The lounge light is on. " * 60).strip()
capped = prepare_for_tts(long_reply, 500)
check("respects the cap", len(capped) <= 500, str(len(capped)))
check("cuts on a sentence end", capped.endswith("."), repr(capped[-40:]))
check("0 means uncapped", len(prepare_for_tts(long_reply, 0)) == len(long_reply),
      str(len(prepare_for_tts(long_reply, 0))))
no_sentence = "word " * 300
hard = prepare_for_tts(no_sentence, 500)
check("hard cut when no sentence end is near", 0 < len(hard) <= 500, str(len(hard)))

# --- 6. Degenerate input -----------------------------------------------------
print("\nDegenerate input")
check("empty string", prepare_for_tts("", 500) == "")
check("whitespace only", prepare_for_tts("   \n\n ", 500) == "")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURE(S):")
    for failure in FAILS:
        print("  -", failure)
    sys.exit(1)
print("All speech checks passed.")
