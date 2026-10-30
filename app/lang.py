"""Which of the two languages a piece of text is in.

Whisper may guess any of ~99 languages for a short clip; this system only needs
English or Kiswahili. Unlike Arabic and English, those two share the Latin
script, so text that did not come from Whisper cannot be told apart by
characters and is judged by vocabulary instead.
"""
import re

# Everyday Kiswahili and Sheng that rarely turns up in an English message.
# Short, ambiguous words ("na", "ya", "si") are left out on purpose: they occur
# inside ordinary English text and would send English replies to the Swahili
# voice. Missing a Swahili message costs an accent; misreading an English one
# costs intelligibility, so this leans towards English.
_SWAHILI_WORDS = re.compile(
    r"\b(niaje|vipi|mambo|habari|sasa|sawa|poa|fiti|manze|buda|wacha|pole|"
    r"asante|karibu|ndio|ndiyo|hapana|tafadhali|leo|jana|kesho|wapi|nani|"
    r"lini|nini|tuma|ujumbe|jumbe|meseji|nipigie|nitakuambia|nimeshika|"
    r"uko|niko|yako|yangu|kwako|rafiki|nakuja|tuonane|baadaye|kwanza|bado|"
    r"haraka|nimechelewa|sijui|utakuja|unaenda|umefika|twende|asubuhi|jioni)\b",
    re.I,
)


def pick_language(info) -> str:
    """info: faster-whisper's TranscriptionInfo (language, all_language_probs)."""
    if info.language in ("en", "sw"):
        return info.language
    probs = dict(getattr(info, "all_language_probs", None) or [])
    return "sw" if probs.get("sw", 0) > probs.get("en", 0) else "en"


def looks_swahili(text: str) -> bool:
    """For text with no Whisper guess behind it, such as a typed reply."""
    return bool(_SWAHILI_WORDS.search(text or ""))
