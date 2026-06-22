"""Parse one StS2 .run JSON file into a flattened (run_row, card_event_rows) pair.

Design notes (kept here so they survive future edits):
 - Defensive for schema_version 8 AND 9 (both present in the user's data).
   Every nested .get() has a default; never KeyError on missing optional fields.
 - LOCAL USER index resolution: match str(players[i].id) against the Steam ID
   carried in from the save-folder path. Fallback to players[0] (100% reliable
   in the recon sample of 53 co-op runs).
 - FLOOR is CUMULATIVE across acts. There is no explicit `floor` JSON field.
   Walk map_point_history in order and number 1, 2, 3, … . For picked cards
   you could read `floor_added_to_deck` directly, but we compute it positionally
   so the same logic applies to non-pick options in the same reward.
 - reward_event_id groups all options offered in a single reward. Format:
   "<run_id>:<act_index>:<map_point_index>". Skip = a group with no
   was_picked=1 (computed downstream, not stored as a row).
 - For card extraction we only walk the LOCAL user's player_stats[i]; other
   players' picks aren't ours.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunParseError(Exception):
    """Raised when a .run file cannot be turned into a valid run row."""


# Map point types where card_choices can appear (per recon).
# (Used only for sanity; we don't filter here — we just record whatever appears.)
CARD_REWARD_MP_TYPES = {"monster", "elite", "boss", "shop", "ancient", "unknown"}


def _get(d: Any, key: str, default=None):
    """Safe dict.get that tolerates None passed in for d."""
    if isinstance(d, dict):
        return d.get(key, default)
    return default


def resolve_local_player_index(players: list, local_steam_id: str | None) -> int:
    """Pick the players[] index that represents the local user.

    Primary: match by `id` field equal to the local Steam ID.
    Fallback: index 0 (verified 100% correct across all 53 co-op runs in recon).
    """
    if local_steam_id:
        for i, p in enumerate(players):
            pid = _get(p, "id")
            if pid is None:
                continue
            if str(pid) == str(local_steam_id):
                return i
    return 0


def parse_run(
    data: dict,
    *,
    local_steam_id: str | None,
    source_file: str,
    imported_at: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Turn one parsed .run JSON object into (run_row, card_event_rows, room_event_rows).

    Raises RunParseError if required fields are missing or unusable.
    """
    if not isinstance(data, dict):
        raise RunParseError("top-level JSON is not an object")

    start_time = data.get("start_time")
    if start_time is None:
        raise RunParseError("missing start_time (used as run_id)")
    run_id = int(start_time)

    players = data.get("players") or []
    if not isinstance(players, list) or not players:
        raise RunParseError("missing or empty players[]")

    local_idx = resolve_local_player_index(players, local_steam_id)
    local_player = players[local_idx]
    character = _get(local_player, "character")
    if not character:
        raise RunParseError(f"local player at index {local_idx} has no character")

    mph = data.get("map_point_history") or []
    if not isinstance(mph, list):
        mph = []
    acts_reached = len(mph)
    floors_reached = sum(len(act) if isinstance(act, list) else 0 for act in mph)

    win = 1 if data.get("win") else 0
    was_abandoned = 1 if data.get("was_abandoned") else 0
    is_multiplayer = 1 if len(players) > 1 else 0

    run_row = {
        "run_id": run_id,
        "seed": data.get("seed"),
        "start_time": run_id,
        "run_time": data.get("run_time"),
        "character": character,
        "ascension": data.get("ascension"),
        "build_id": data.get("build_id"),
        "schema_version": data.get("schema_version"),
        "game_mode": data.get("game_mode") or "unknown",
        "win": win,
        "was_abandoned": was_abandoned,
        "is_multiplayer": is_multiplayer,
        "num_players": len(players),
        "acts_reached": acts_reached,
        "floors_reached": floors_reached,
        "killed_by_encounter": data.get("killed_by_encounter"),
        "killed_by_event": data.get("killed_by_event"),
        "local_player_index": local_idx,
        "source_file": source_file,
        "imported_at": imported_at or datetime.now(timezone.utc).isoformat(),
    }

    card_events = _extract_card_events(run_id, mph, local_idx)
    room_events = _extract_room_events(run_id, mph, local_idx)
    return run_row, card_events, room_events


def _extract_card_events(run_id: int, mph: list, local_idx: int) -> list[dict]:
    """Walk map_point_history, compute cumulative floor, emit one row per card option."""
    rows: list[dict] = []
    floor_counter = 0  # incremented per map point as we walk
    for act_index, act in enumerate(mph):
        if not isinstance(act, list):
            continue
        for mp_index, mp in enumerate(act):
            floor_counter += 1
            if not isinstance(mp, dict):
                continue
            mp_type = mp.get("map_point_type") or "unknown"
            pstats_list = mp.get("player_stats") or []
            # player_stats[] is index-aligned with players[] — pull just the local user's
            if not isinstance(pstats_list, list) or local_idx >= len(pstats_list):
                continue
            pstats = pstats_list[local_idx]
            if not isinstance(pstats, dict):
                continue
            choices = pstats.get("card_choices")
            if not isinstance(choices, list) or not choices:
                continue
            reward_event_id = f"{run_id}:{act_index}:{mp_index}"
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                card = choice.get("card")
                if not isinstance(card, dict):
                    continue
                card_id = card.get("id")
                if not card_id:
                    continue
                rows.append({
                    "run_id": run_id,
                    "reward_event_id": reward_event_id,
                    "act_index": act_index,
                    "map_point_index": mp_index,
                    "floor": floor_counter,
                    "source_type": mp_type,
                    "card_id": card_id,
                    "was_picked": 1 if choice.get("was_picked") else 0,
                })
    return rows


def _extract_room_events(run_id: int, mph: list, local_idx: int) -> list[dict]:
    """Walk map_point_history and emit one row per room (= per map point) for the
    local user, capturing damage / healing / gold / HP / turns."""
    rows: list[dict] = []
    floor_counter = 0
    for act_index, act in enumerate(mph):
        if not isinstance(act, list):
            continue
        for mp_index, mp in enumerate(act):
            floor_counter += 1
            if not isinstance(mp, dict):
                continue
            mp_type = mp.get("map_point_type") or "unknown"
            rooms = mp.get("rooms") or []
            first_room = rooms[0] if isinstance(rooms, list) and rooms else {}
            if not isinstance(first_room, dict):
                first_room = {}
            pstats_list = mp.get("player_stats") or []
            if not isinstance(pstats_list, list) or local_idx >= len(pstats_list):
                continue
            pstats = pstats_list[local_idx]
            if not isinstance(pstats, dict):
                continue
            rows.append({
                "run_id": run_id,
                "act_index": act_index,
                "map_point_index": mp_index,
                "floor": floor_counter,
                "map_point_type": mp_type,
                "room_type": first_room.get("room_type"),
                "encounter_model_id": first_room.get("model_id"),
                "damage_taken": int(pstats.get("damage_taken") or 0),
                "hp_healed": int(pstats.get("hp_healed") or 0),
                "current_hp": pstats.get("current_hp"),
                "max_hp": pstats.get("max_hp"),
                "gold_gained": int(pstats.get("gold_gained") or 0),
                "gold_spent": int(pstats.get("gold_spent") or 0),
                "turns_taken": first_room.get("turns_taken"),
            })
    return rows


def parse_file(
    path: Path,
    *,
    local_steam_id: str | None,
    imported_at: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Convenience: read + parse a .run file from disk."""
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_run(
        data,
        local_steam_id=local_steam_id,
        source_file=str(path),
        imported_at=imported_at,
    )
