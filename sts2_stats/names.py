"""Human-readable display names for card / character IDs.

IDs in the save data look like ``CARD.HELIX_DRILL`` or ``CHARACTER.IRONCLAD``.
Default prettify: strip the ``PREFIX.``, split on ``_``, title-case each word
(``CARD.HELIX_DRILL`` -> ``Helix Drill``). A hand-maintained JSON overrides
file (``card_name_overrides.json`` at the repo root) wins when the auto-result
is wrong or ugly. SPEC §10 calls for exactly this approach.

The overrides file is optional; if it's missing or malformed we silently fall
back to the auto-prettifier so the dashboard never breaks over a display name.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# Repo root = parent of the sts2_stats package directory.
_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "card_name_overrides.json"


@lru_cache(maxsize=1)
def _overrides() -> dict:
    try:
        with _OVERRIDES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _strip_prefix(raw: str) -> str:
    """`CARD.HELIX_DRILL` -> `HELIX_DRILL`; leaves un-prefixed ids untouched."""
    return raw.split(".", 1)[1] if "." in raw else raw


# Joining words kept lowercase mid-title (so SPOILS_OF_BATTLE -> "Spoils of
# Battle", not "Spoils Of Battle"). The first word is always capitalized.
_SMALL_WORDS = {"of", "the", "a", "an", "and", "to", "in", "on", "for", "with", "vs", "at"}


def _titleize(token: str) -> str:
    words = [w for w in token.split("_") if w]
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if i > 0 and lw in _SMALL_WORDS:
            out.append(lw)
        else:
            out.append(w.capitalize())
    return " ".join(out)


def pretty_card_name(card_id: str | None) -> str:
    if not card_id:
        return "—"
    overrides = _overrides()
    if card_id in overrides:
        return overrides[card_id]
    return _titleize(_strip_prefix(card_id)) or card_id


def pretty_character_name(char_id: str | None) -> str:
    if not char_id:
        return "—"
    return _titleize(_strip_prefix(char_id)) or char_id


def pretty_relic_name(relic_id: str | None) -> str:
    if not relic_id:
        return "—"
    overrides = _overrides()
    if relic_id in overrides:
        return overrides[relic_id]
    return _titleize(_strip_prefix(relic_id)) or relic_id


def pretty_potion_name(potion_id: str | None) -> str:
    if not potion_id:
        return "—"
    overrides = _overrides()
    if potion_id in overrides:
        return overrides[potion_id]
    return _titleize(_strip_prefix(potion_id)) or potion_id
