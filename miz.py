"""
MIZ archive helpers for DCS World Mission Message Editor.

A .miz file is a ZIP archive that may contain one or more dictionary files at:
    l10n/<locale>/dictionary

This module provides:
  - open_miz()  — read all dictionaries from a .miz file into memory
  - save_miz()  — write modified dictionaries back into the .miz archive
                  (all other archive entries are preserved unchanged)
"""

from __future__ import annotations

import io
import zipfile
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Dict

import parser as dict_parser

# Path pattern inside the archive: l10n/<locale>/dictionary
_L10N_PREFIX = "l10n/"
_DICT_FILENAME = "dictionary"


def _dict_zip_path(locale: str) -> str:
    """Return the in-archive path for a given locale's dictionary."""
    return f"{_L10N_PREFIX}{locale}/{_DICT_FILENAME}"


def open_miz(miz_path: Path) -> Dict[str, "OrderedDict[str, str]"]:
    """Open a .miz archive and return {locale: entries} for every dictionary found.

    Raises:
        ValueError: if no l10n/*/dictionary entries are found in the archive.
        zipfile.BadZipFile: if the file is not a valid ZIP archive.
    """
    result: Dict[str, OrderedDict[str, str]] = {}

    with zipfile.ZipFile(miz_path, "r") as zf:
        for name in zf.namelist():
            parts = PurePosixPath(name).parts
            # Expected structure: ('l10n', '<locale>', 'dictionary')
            if (
                len(parts) == 3
                and parts[0] == "l10n"
                and parts[2] == _DICT_FILENAME
            ):
                locale = parts[1]
                data = zf.read(name)
                result[locale] = dict_parser.parse_bytes(data)

    if not result:
        raise ValueError(
            f"В архиве «{miz_path.name}» не найдено ни одного файла l10n/*/dictionary."
        )

    return result


def save_miz(
    miz_path: Path,
    locale: str,
    entries: "OrderedDict[str, str]",
) -> None:
    """Overwrite a single locale's dictionary inside the .miz archive.

    The archive is rewritten in-place: all existing entries are preserved,
    only the target dictionary file is replaced with the new content.

    Args:
        miz_path: path to the .miz file.
        locale:   locale name (subdirectory under l10n/).
        entries:  updated key→value mapping to serialize and store.
    """
    target_entry = _dict_zip_path(locale)
    new_content = dict_parser.serialize_bytes(entries)

    # Read the entire archive into memory, then rewrite it with the updated entry.
    buf = io.BytesIO()
    with zipfile.ZipFile(miz_path, "r") as zf_in:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                if item.filename == target_entry:
                    zf_out.writestr(item, new_content)
                else:
                    zf_out.writestr(item, zf_in.read(item.filename))

    # Atomically replace the original file
    miz_path.write_bytes(buf.getvalue())


def delete_locale_from_miz(miz_path: Path, locale: str) -> None:
    """Remove the entire l10n/<locale>/ subtree from the .miz archive.

    All other archive entries are preserved unchanged.

    Args:
        miz_path: path to the .miz file.
        locale:   locale name (subdirectory under l10n/) to delete.

    Raises:
        ValueError: if the locale is not found in the archive.
    """
    prefix = f"{_L10N_PREFIX}{locale}/"

    buf = io.BytesIO()
    removed = 0
    with zipfile.ZipFile(miz_path, "r") as zf_in:
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf_out:
            for item in zf_in.infolist():
                if item.filename.startswith(prefix):
                    removed += 1  # skip — this entry belongs to the deleted locale
                else:
                    zf_out.writestr(item, zf_in.read(item.filename))

    if removed == 0:
        raise ValueError(
            f"Локаль «{locale}» не найдена в архиве «{miz_path.name}»."
        )

    miz_path.write_bytes(buf.getvalue())
