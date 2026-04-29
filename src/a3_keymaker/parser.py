"""Parse the SQF clipboard dump produced by ``extract_all.sqf``.

The dump is a text blob:

    A3KM_OK
    vanilla_categories=[[...], ...]
    mappings=[[...], ...]
    vanilla_engine=[[...], ...]
    addons=[[...], ...]

Each section value is an SQF array literal — almost JSON, but strings escape
an embedded double-quote by doubling it. E.g. the SQF text containing five
double-quotes around W (one outer pair plus a doubled-quote escape on each
side around the W) represents the 3-char Python string consisting of a
quote, the letter W, and a quote.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


class DumpParseError(Exception):
    """Raised when the dump can't be parsed (wrong format, missing sections, etc.)."""


@dataclass
class ParsedDump:
    """Raw sections from the SQF dump, before any merging or label resolution."""

    vanilla_categories: list   # [[idx, name, data, count, [[row_idx, label, lbData], ...]], ...]
    mappings: list             # [[id, key_text, [preset_names]], ...]
    vanilla_engine: list       # [[id, key_text], ...]
    cfg_user_actions: list     # [[id, displayName, key_text], ...]
    addons: list               # [[idx, name, data, count, [[label, key_text], ...]], ...]


_SECTION_NAMES = [
    "vanilla_categories",
    "mappings",
    "vanilla_engine",
    "cfg_user_actions",
    "addons",
]
# Sections that older dump formats may not contain. parse_dump returns an
# empty list for these instead of raising.
_OPTIONAL_SECTIONS = {"cfg_user_actions"}


def parse_dump(text: str) -> ParsedDump:
    """Parse an A3KM_OK dump text into structured Python lists."""
    text = text.strip()
    if not text.startswith("A3KM_OK"):
        # Be helpful: surface the actual marker so the user knows which run state they captured.
        first_line = text.split("\n", 1)[0]
        raise DumpParseError(
            f"dump does not start with A3KM_OK (got {first_line!r}). "
            "Re-run extract_all.sqf and paste your clipboard *after* the dialog stops cycling."
        )

    sections = {}
    for name in _SECTION_NAMES:
        sections[name] = _extract_section(text, name, optional=name in _OPTIONAL_SECTIONS)

    return ParsedDump(
        vanilla_categories=sections["vanilla_categories"],
        mappings=sections["mappings"],
        vanilla_engine=sections["vanilla_engine"],
        cfg_user_actions=sections["cfg_user_actions"],
        addons=sections["addons"],
    )


def _extract_section(text: str, name: str, optional: bool = False) -> list:
    """Find ``<name>=<sqf_array>`` and parse the array.

    If ``optional`` is True and the section is missing, return ``[]``
    instead of raising — supports older dump formats that lack newer
    sections.
    """
    # Sections are newline-delimited; we look for "name=[..." up to the next
    # newline+letter+= (next section start) or end-of-text.
    pattern = rf"{re.escape(name)}=(\[.*?\])(?:\n[a-z_]+=|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        if optional:
            return []
        raise DumpParseError(f"section {name!r} not found in dump")
    return _parse_sqf_array(m.group(1))


def _parse_sqf_array(s: str) -> list:
    """Convert an SQF array literal to a Python list.

    SQF strings escape an embedded double-quote by doubling it; we rewrite
    each SQF string into a JSON-escaped equivalent and then ``json.loads``
    the result.
    """
    json_str = _sqf_to_json(s)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise DumpParseError(f"failed to parse SQF array as JSON: {e}") from e


def _sqf_to_json(s: str) -> str:
    """Walk the SQF text and replace each SQF string with its JSON form.

    Reads character-by-character so we correctly handle ``""`` (escaped quote)
    inside a string vs. ``"" ""`` (two empty strings). Backslashes in literal
    strings (e.g. file paths in the deep dump) are JSON-escaped. Mojibake
    introduced by the Windows clipboard re-encoding round-trip is fixed
    per-string before serialization.
    """
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == '"':
            # Start of an SQF string — read until unescaped closing quote.
            buf: list[str] = []
            i += 1
            while i < n:
                if s[i] == '"':
                    # Either an escaped quote (""), or the end of the string.
                    if i + 1 < n and s[i + 1] == '"':
                        buf.append('"')
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    buf.append(s[i])
                    i += 1
            content = _try_fix_mojibake("".join(buf))
            # JSON-escape the content (handles \ and " and control chars).
            out.append(json.dumps(content))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _build_cp1252_to_byte_map() -> dict[str, int]:
    """Return a Unicode-char → byte-value map covering all 256 CP1252 positions.

    Five CP1252 positions (0x81, 0x8D, 0x8F, 0x90, 0x9D) are formally
    undefined — Python's cp1252 codec decodes those bytes to the matching
    C1 control codepoint (e.g. byte 0x90 → U+0090) but REFUSES to encode
    those codepoints back. We populate them manually so the round-trip is
    symmetric and lossless.
    """
    table: dict[str, int] = {}
    for b in range(256):
        try:
            ch = bytes([b]).decode("cp1252")
        except UnicodeDecodeError:
            # Should not happen — all of cp1252 decodes per the table above.
            ch = chr(b)
        table[ch] = b
    # Defensive: ensure each undefined-position C1 control maps to itself.
    for b in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
        table.setdefault(chr(b), b)
    return table


_CP1252_TO_BYTE = _build_cp1252_to_byte_map()


def _try_fix_mojibake(s: str) -> str:
    """Reverse the UTF-8 → CP1252 → UTF-8 double-encoding that the Windows
    clipboard pipeline applies to non-ASCII characters.

    Arma writes UTF-8 to the clipboard. Some clipboard / text-editor stop
    along the way reinterprets those bytes as CP1252, then writes them back
    as UTF-8. Result: the SQF arrow ``↑`` (UTF-8 ``E2 86 91``) lands in
    the dump file as the mojibake string ``â†'`` — i.e. UTF-8 of three
    CP1252 characters. Mapping each character back to its CP1252 byte
    recovers the original UTF-8 bytes; decoding those as UTF-8 recovers
    the original character.

    Returns the recovered string only when EVERY character maps to a
    CP1252 byte AND the resulting bytes form valid UTF-8 AND the result
    differs from the input. Otherwise returns the original — strings that
    are genuine non-ASCII text (e.g. "café") fail the UTF-8 decode and
    pass through unchanged.
    """
    if not s:
        return s
    try:
        raw = bytes(_CP1252_TO_BYTE[c] for c in s)
    except KeyError:
        # Some character isn't in the CP1252 map — can't be mojibake of
        # this flavor.
        return s
    try:
        recovered = raw.decode("utf-8")
    except UnicodeDecodeError:
        return s
    return recovered if recovered != s else s
