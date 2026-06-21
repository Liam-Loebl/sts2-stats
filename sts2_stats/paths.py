"""Locate the StS2 run-history folder(s) and extract the local Steam ID.

Auto-detects across machines (Windows): we glob under %APPDATA% so the same
code runs unchanged on the laptop and the desktop — username and steamid are
never hardcoded.
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path


_STEAMID_RE = re.compile(r"^\d{17}$")


def _appdata_root() -> Path:
    """Resolve the user's APPDATA\\Roaming folder cross-environment."""
    raw = os.environ.get("APPDATA")
    if raw:
        return Path(raw)
    return Path.home() / "AppData" / "Roaming"


def find_history_dirs() -> list[Path]:
    """Return every StS2 run-history directory found under APPDATA.

    Path shape: %APPDATA%\\SlayTheSpire2\\steam\\<steamid>\\profile*\\saves\\history
    A user normally has exactly one, but we tolerate multiple profiles.
    """
    root = _appdata_root()
    pattern = str(root / "SlayTheSpire2" / "steam" / "*" / "profile*" / "saves" / "history")
    return sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_dir())


def steam_id_from_path(history_dir: Path) -> str | None:
    """Pull the 17-digit Steam ID out of a history-folder path.

    Returns None if the path doesn't contain a recognizable steam segment.
    """
    parts = history_dir.parts
    for i, segment in enumerate(parts):
        if segment.lower() == "steam" and i + 1 < len(parts):
            candidate = parts[i + 1]
            if _STEAMID_RE.match(candidate):
                return candidate
    return None


def iter_run_files(history_dir: Path):
    """Yield all real .run files in a history dir, skipping backups and corrupt in-progress saves."""
    for p in sorted(history_dir.glob("*.run")):
        name = p.name
        if name.endswith(".backup"):
            continue
        if "corrupt" in name.lower():
            continue
        yield p
