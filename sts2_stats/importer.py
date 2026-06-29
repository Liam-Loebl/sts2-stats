"""Scan StS2 history folder(s) and idempotently upsert every .run into SQLite.

Re-running this on the same data leaves the DB identical — `upsert_run`
deletes the run's prior card_events via ON DELETE CASCADE, then re-inserts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .db import connect, log_import_error, upsert_run
from .parser import parse_file, RunParseError
from .paths import find_history_dirs, iter_run_files, steam_id_from_path


def import_all(db_path: Path, history_dirs: Iterable[Path] | None = None) -> dict:
    """Import every run from the given history dirs (or auto-discover).

    Returns a small summary dict (counts only — full sanity report lives in db.py).
    """
    history_dirs = list(history_dirs) if history_dirs is not None else find_history_dirs()
    if not history_dirs:
        return {"history_dirs": [], "imported": 0, "errors": 0, "skipped": 0}

    conn = connect(Path(db_path))
    imported = 0
    errors = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        for hist in history_dirs:
            steamid = steam_id_from_path(hist)
            for path in iter_run_files(hist):
                try:
                    run_row, card_events, room_events, relic_events, potion_events = parse_file(
                        path,
                        local_steam_id=steamid,
                        imported_at=now_iso,
                    )
                except (RunParseError, ValueError) as e:
                    log_import_error(conn, str(path), f"{type(e).__name__}: {e}", now_iso)
                    errors += 1
                    continue
                except Exception as e:  # JSON decode errors, file IO, anything else
                    log_import_error(conn, str(path), f"{type(e).__name__}: {e}", now_iso)
                    errors += 1
                    continue
                upsert_run(conn, run_row, card_events, room_events, relic_events, potion_events)
                imported += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "history_dirs": [str(p) for p in history_dirs],
        "imported": imported,
        "errors": errors,
    }
