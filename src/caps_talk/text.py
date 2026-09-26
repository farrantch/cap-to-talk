"""Text cleanup used immediately before X11 insertion."""

from __future__ import annotations

_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
}


def normalize_for_typing(text: str) -> str:
    """Normalize typography while retaining intentional paragraph breaks."""
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]

    normalized: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        normalized.append(line)
        previous_blank = blank

    return "\n".join(normalized).strip()


def strip_wrapping_quotes(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        return text[1:-1].strip()
    return text
