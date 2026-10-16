"""Turn a Jarvis chat reply into something safe to hand to text-to-speech.

`/v1/chat/completions` returns `content` as **chat** text: Markdown, emoji, file
paths and Hermes's own turn-end advisories all belong there, because the normal
consumer is a screen. Hermes never speaks that string raw either — every one of
its own voice surfaces (`gateway/platforms/base.py`, `hermes_cli/voice.py`,
`tools/tts_tool.py`) runs it through `tools/tts_text_normalize.prepare_spoken_text`
first. This adapter is a voice surface that was skipping that step, which is how
the file-mutation verifier footer reached a speaker (DAV-28).

So we run Hermes's own normalizer, vendored byte-for-byte rather than rewritten,
and then apply the one policy that is ours rather than theirs: a hard ceiling on
how many characters we are willing to send to a per-character TTS provider.

`tts_text_normalize.py` in this folder is an unmodified copy of
`tools/tts_text_normalize.py` from NousResearch/hermes-agent at commit
`acc3cada0da86c81efc8aa6c5a291989549ca900`. Its git blob SHA-1 is
`511e7bd877b9b41880483069e1e316c676c1d50a`; to check it has not drifted:

    git hash-object custom_components/jarvis_conversation/tts_text_normalize.py

It is pure stdlib (`html`, `re`), so vendoring adds no requirement.
"""

from __future__ import annotations

import re

from .tts_text_normalize import prepare_spoken_text

# Prefer to cut at the end of a sentence rather than mid-word. Only used when the
# reply is over the cap, which a one-or-two-sentence answer never is.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")

# A cut that would throw away most of the answer is worse than a slightly long
# one: below this fraction of the cap we accept a hard cut instead.
_MIN_SENTENCE_CUT = 0.6


def prepare_for_tts(content: str, max_chars: int = 0) -> str:
    """Return speakable text for `content`, or "" if nothing in it is speakable.

    An empty return is a real outcome, not an edge case: a turn whose entire
    `content` was a verifier footer or a `<think>` block normalises to nothing,
    and the caller must treat that as "Jarvis did not answer" rather than send
    an empty string to the speaker.
    """
    # max_chars=None: let the caller's own cap below be the only one, so the
    # upstream default of 4000 cannot silently override a smaller house limit.
    spoken = prepare_spoken_text(content or "", max_chars=None).strip()
    if not spoken or max_chars <= 0 or len(spoken) <= max_chars:
        return spoken

    window = spoken[:max_chars]
    ends = [match.end() for match in _SENTENCE_END_RE.finditer(window)]
    if ends and ends[-1] >= max_chars * _MIN_SENTENCE_CUT:
        return window[: ends[-1]].strip()
    return window.rstrip()
