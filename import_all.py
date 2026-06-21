"""Top-level entrypoint: auto-discover the StS2 history folder, import every run
into a local SQLite database, and print a sanity report.

Usage:
    python import_all.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the sibling package importable when this script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sts2_stats.db import connect, print_sanity_report, sanity_report
from sts2_stats.importer import import_all
from sts2_stats.paths import find_history_dirs

DB_PATH = Path(__file__).resolve().parent / "sts2_stats.sqlite"


def main() -> int:
    dirs = find_history_dirs()
    if not dirs:
        print("ERROR: no StS2 run-history folder found under %APPDATA%.")
        print("       Have you launched StS2 on this machine? (Steam Cloud must have synced down.)")
        return 1

    print(f"Found {len(dirs)} history dir(s):")
    for d in dirs:
        print(f"  {d}")
    print()

    print(f"Importing into: {DB_PATH}")
    result = import_all(DB_PATH, history_dirs=dirs)
    print(f"  Imported: {result['imported']}    Errors: {result['errors']}")
    print()

    # Open a fresh read-only-ish connection to render the sanity report.
    conn = connect(DB_PATH)
    try:
        print_sanity_report(sanity_report(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
