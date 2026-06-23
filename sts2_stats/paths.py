"""Locate the StS2 run-history folder(s) and extract the local Steam ID.

Auto-detects across machines and OSes: we glob the known Steam save layouts so
the same code runs unchanged on Windows, macOS, and Linux — username, steamid,
and profile number are never hardcoded.

Layouts:
 - Windows: %APPDATA%\\SlayTheSpire2\\steam\\<steamid>\\profile*\\saves\\history
 - macOS:   ~/Library/Application Support/Steam/userdata/<id>/2868840/remote/profile*/saves/history
 - Linux:   ~/.local/share/Steam (or ~/.steam/steam) /userdata/<id>/2868840/remote/profile*/saves/history
"""
from __future__ import annotations

import glob
import os
import re
from pathlib import Path


_STEAMID_RE = re.compile(r"^\d{17}$")

# StS2 Steam app id — the `userdata/<id>/<appid>/remote` segment on macOS/Linux.
_STS2_APP_ID = "2868840"


def _history_globs() -> list[str]:
    """Every glob pattern that could contain an StS2 run-history dir, across OSes."""
    patterns: list[str] = []

    # Windows: %APPDATA%\SlayTheSpire2\steam\<steamid>\profile*\saves\history
    appdata = os.environ.get("APPDATA")
    appdata_root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    patterns.append(
        str(appdata_root / "SlayTheSpire2" / "steam" / "*" / "profile*" / "saves" / "history")
    )

    # macOS + Linux: <steam-root>/userdata/<id>/<appid>/remote/profile*/saves/history
    home = Path.home()
    steam_roots = [
        home / "Library" / "Application Support" / "Steam",  # macOS
        home / ".local" / "share" / "Steam",                 # Linux (native)
        home / ".steam" / "steam",                           # Linux (legacy symlink)
    ]
    for root in steam_roots:
        patterns.append(
            str(root / "userdata" / "*" / _STS2_APP_ID / "remote" / "profile*" / "saves" / "history")
        )

    return patterns


def find_history_dirs() -> list[Path]:
    """Return every StS2 run-history directory found across all known OS layouts.

    A user normally has exactly one, but we tolerate multiple profiles/machines.
    """
    found: set[Path] = set()
    for pattern in _history_globs():
        for p in glob.glob(pattern):
            path = Path(p)
            if path.is_dir():
                found.add(path)
    return sorted(found)


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
