"""
Parser and serializer for DCS World mission dictionary files.

Format example (single-line value):
    ["DictKey_18"] = "Some text",

Format example (multi-line value — Lua line continuation with backslash):
    ["DictKey_24"] = "Line one\\
\\
Line two",

Inside the file each logical line that ends with a single backslash immediately
before the newline is a continuation: the value spans multiple physical lines.
We store values internally with the literal two-character sequence  \\<newline>
preserved, so round-tripping to disk is lossless.  The UI layer is responsible
for deciding how to display / edit that sequence.
"""

import re
from pathlib import Path
from collections import OrderedDict

# Matches the opening of an entry:  ["SomeKey"] = "...
# The value may continue on the next physical line (Lua line-continuation).
_ENTRY_START_RE = re.compile(r'^\s*\["(?P<key>[^"]+)"\]\s*=\s*"(?P<value>.*)')

# A physical line that closes the value:  ...text",   or   ...",
_ENTRY_END_RE = re.compile(r'^(?P<value>.*)",\s*$')

# Lua line-continuation: physical line ends with a single backslash
_CONTINUATION = "\\"


def parse_text(text: str) -> "OrderedDict[str, str]":
    """Parse DCS dictionary text and return an ordered key→value mapping.

    Handles multi-line values produced by Lua line-continuation (trailing \\).
    The internal representation keeps the literal ``\\\\\\n`` sequence so that
    serialization is lossless.
    """
    entries: OrderedDict[str, str] = OrderedDict()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ENTRY_START_RE.match(line)
        if m:
            key = m.group("key")
            partial = m.group("value")  # everything after the opening quote

            # Check whether this physical line already closes the value
            # (ends with  ",  possibly with trailing spaces)
            if partial.endswith('",') or partial.endswith('",'):
                # Single-line value: strip the closing  ",
                value = partial[:-2] if partial.endswith('",') else partial.rstrip().rstrip(',').rstrip('"')
                # More robust: use the end regex on the partial tail
                em = _ENTRY_END_RE.match(partial)
                if em:
                    value = em.group("value")
                else:
                    # Fallback: strip trailing  ",
                    value = partial.rstrip()
                    if value.endswith('",'):
                        value = value[:-2]
                    elif value.endswith('"'):
                        value = value[:-1]
                entries[key] = value
                i += 1
                continue

            # Multi-line value: the opening line ends with  \  (continuation)
            # Accumulate physical lines until we find the closing  ",
            value_parts = [partial]  # first fragment (after opening quote)
            i += 1
            while i < len(lines):
                cont_line = lines[i]
                em = _ENTRY_END_RE.match(cont_line)
                if em:
                    # This line closes the value
                    value_parts.append(em.group("value"))
                    i += 1
                    break
                else:
                    # Continuation line — keep as-is (including trailing \)
                    value_parts.append(cont_line)
                    i += 1

            # Join with \n to reconstruct the original multi-line text
            entries[key] = "\n".join(value_parts)
            continue

        i += 1

    return entries


def parse(path: Path) -> "OrderedDict[str, str]":
    """Read a DCS dictionary file and return an ordered key→value mapping."""
    return parse_text(path.read_text(encoding="utf-8"))


def parse_bytes(data: bytes) -> "OrderedDict[str, str]":
    """Parse DCS dictionary from raw bytes (e.g. read from a ZIP archive)."""
    return parse_text(data.decode("utf-8"))


def serialize(entries: "OrderedDict[str, str]") -> str:
    """Serialize key→value mapping back to the DCS dictionary format.

    Multi-line values (containing ``\\n``) are written as Lua line-continuations:
    each internal newline becomes a physical newline in the file, so the
    backslash that precedes it (already part of the stored value) acts as the
    Lua continuation marker.
    """
    lines = ["dictionary = ", "{"]
    for key, value in entries.items():
        lines.append(f'\t["{key}"] = "{value}",')
    lines.append("} -- end of dictionary")
    return "\n".join(lines) + "\n"


def serialize_bytes(entries: "OrderedDict[str, str]") -> bytes:
    """Serialize key→value mapping to UTF-8 bytes for writing into a ZIP archive."""
    return serialize(entries).encode("utf-8")


def save(path: Path, entries: "OrderedDict[str, str]") -> None:
    """Write entries to the given path in DCS dictionary format."""
    path.write_text(serialize(entries), encoding="utf-8")
