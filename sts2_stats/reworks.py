"""Card-rebalance 'valid-from' filter (SPEC §10).

When a card is reworked in a patch, its pre-rework data shouldn't pollute its
current stats. `card_reworks.json` (repo root) maps a card_id to the minimum
build_id its current form is valid from; events from earlier builds are excluded
from that card's stats. Cards not listed use all their data. Hand-maintained —
we do NOT auto-detect card changes.

build_ids look like "v0.101.0"; they're parsed to integer tuples and padded so
"v0.98.3" < "v0.101.0" compares correctly. Anything unparseable is treated as
"include" (fail open) so a weird build id never silently drops data.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "card_reworks.json"


@lru_cache(maxsize=1)
def _reworks() -> dict[str, str]:
    try:
        with _PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, str)}


def _parse_build(build_id) -> tuple[int, ...] | None:
    """`v0.101.0` -> (0, 101, 0, 0), padded to length 4. None if unparseable."""
    if not build_id:
        return None
    parts = str(build_id).lstrip("vV").split(".")
    out: list[int] = []
    for p in parts:
        digits = "".join(ch for ch in p if ch.isdigit())
        if digits == "":
            return None
        out.append(int(digits))
    if not out:
        return None
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def event_excluded(card_id: str, build_id) -> bool:
    """True if this card event predates the card's valid-from build (a rework)."""
    valid_from = _reworks().get(card_id)
    if not valid_from:
        return False
    vf = _parse_build(valid_from)
    bb = _parse_build(build_id)
    if vf is None or bb is None:
        return False  # can't compare -> include (fail open)
    return bb < vf


def has_reworks() -> bool:
    return bool(_reworks())
