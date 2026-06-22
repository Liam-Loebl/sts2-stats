# Slay the Spire 2 Stats

> A local-first stats tool for my Slay the Spire 2 runs, built to find which cards I overrate and which I should be picking more.

Status: Phase 1 (data ingest + storage) complete. Phase 2 (dashboard) next.

## The story

[Jorbs](https://www.twitch.tv/jorbs) is widely regarded as one of the best Slay the Spire players in the world. A week or two after Slay the Spire 2 hit Steam Early Access in March 2026, he started keeping a spreadsheet logging every run he plays: what character, what cards he picked, whether he won. He uses it to find the leaks in his own play. Cards he keeps picking that don't win him games, cards he keeps skipping that would.

I've watched a lot of his videos. I wanted the same feedback loop for my own play, except I didn't want to fill in a spreadsheet by hand after every run. The game already writes a JSON file to disk every time a run ends. The data is right there. I had to get it out.

I'm building it because I want to use it to get better at the game, and because it's the biggest software project I've designed end-to-end so far, with all the design decisions on me (schema, statistical methodology, edge cases I didn't anticipate) instead of following a tutorial.

## What's live right now (Phase 1)

- Auto-detects the StS2 save folder under `%APPDATA%`. Same code works on my laptop and my desktop with no configuration.
- Parses every `.run` JSON file (150 runs so far) and loads them into a local SQLite database.
- Handles both schema versions present in my local runs (v8 and v9). The game has continued to bump the save schema in later patches; covering newer schemas is on the to-do list as I encounter them.
- Co-op aware: each co-op run is stored with a flag, and the local player is identified by matching the Steam ID in the save-folder path against the player IDs inside the run.
- Idempotent: re-running the import is a no-op for runs already in the database.
- Verified end-to-end against the full corpus (150 runs, 9,882 card events). Every topline number in the sanity report matches the counts I had derived by hand from the raw JSON before writing the importer.

The dashboard comes next.

## The interesting parts

Two problems were harder than I expected.

### Survivorship bias in card win rate

The naive way to measure a card is "win rate of runs that picked it." That number is misleading. Cards offered as a reward on Floor 45 are almost always in winning runs, because most losing runs are already dead by Floor 45. The card gets credit for the run surviving, not for helping it survive.

The fix is a metric called **WAR (Wins Above Replacement)**, borrowed from baseball sabermetrics. For each time I pick a card, the contribution is `(actual outcome) - (expected outcome)`, where the expected outcome is my own win rate on that character among runs that reached that floor. Pinning the baseline to the floor strips out the survivorship, so a Floor-45 card only earns positive WAR when picking it does better than the average run that had already gotten that far.

I aggregate WAR per-act and overall in the dashboard. Per-floor data sits in the database (every card event carries its floor), but I don't surface the per-(card, floor) WAR breakdowns. At 150 runs the cells are too noisy to be honest about.

### Measuring preference separately from outcome

WAR measures what wins. It doesn't measure what I *pick*. A card I love but skip half the time still won't show up as overrated in WAR.

So I'm also rating cards with **Elo**. Every card reward screen is a mini-tournament: the card I picked "beats" every alternative on offer, including Skip. The wrinkle: a standard Elo update is one-vs-one, but a reward screen has three or four options. I update pairwise across every (picked, alternative) pair and sum the updates. That structurally rewards picking against a wider field (beating three options is a stronger signal than beating one) without breaking Elo's zero-sum property: every point one card gains, another loses.

### Why the pair matters: the headline insight

WAR measures outcomes; Elo measures my preferences. The interesting cards are the ones where the two metrics disagree:

- High Elo + low WAR: a card I overrate. I keep picking it; it isn't winning me games.
- Low Elo + high WAR: a card I underrate. I usually skip it; when I take it, my runs do better.

Those two lists, against my own play, are what a generic tier list can't give me.

## How it works

```
%APPDATA%/.../saves/history/*.run    (Steam Cloud syncs these between my machines)
              |
              v
       paths.py     -- find save folder, extract local Steam ID
              |
              v
       parser.py    -- JSON -> normalized records (tolerates v8 and v9)
              |
              v
       importer.py  -- idempotent upsert
              |
              v
       sts2_stats.sqlite  (local, per-machine)
              |
              v
       Phase 2+    -- Streamlit dashboard
```

A few design choices worth flagging:

- **Auto-detect, never hardcode.** No usernames or Steam IDs live in source. Each machine builds its own local DB from its own synced copy of the save files. No DB syncing, no cloud server.
- **Dual schema tolerance.** Both v8 and v9 save formats parse behind a single normalized representation, so the rest of the pipeline doesn't have to care which version wrote a given file.
- **Local user resolution in co-op.** I pull the Steam ID from the save-folder path and match it against `players[i].id` inside each run. Falls back to `players[0]` only if no match. Verified safe across all 53 of my co-op runs.
- **Sanity report + verifier.** `import_all.py` ends with a topline report (run counts, win rates, per-character / per-schema / per-build splits) I eyeball after every re-import. For deeper checks, `verify.py` runs a battery of invariants: no NULLs in required columns, FK integrity, co-op local-user resolution on every co-op run, floor math against source JSON, random whole-row spot-checks, and idempotency. It exits non-zero if anything fails. It also runs a soft tone scan on README and SPEC.md against a customizable inventory of AI-prose tells (em-dash density, hedge/filler words, sentence-starting And/But/So, -ly adverb pile-ups, over-bolding, passive voice, corporate jargon, clichés, and more) and reports a per-category summary so I can see where my writing is drifting. Tone hits are soft warnings (the run still passes), but they show up in the same output as the schema checks so I can't ignore them. When the game ships a v10 schema or my prose drifts, I see it immediately.

## Roadmap

- [x] **Phase 1 — Ingest.** Parser, SQLite schema, idempotent importer, sanity-report CLI.
- [ ] **Phase 2 — Overview dashboard.** Themed in-browser dashboard: total runs, per-character tiles, win-rate trends, damage per act.
- [ ] **Phase 3 — Card rankings board.** Pick%, win%, WAR, Elo, all sortable, sample size shown, shrinkage applied to low-N cards.
- [ ] **Phase 4 — Per-card and per-character detail pages.** WAR by act, Elo over time, Elo-vs-WAR scatter.
- [ ] **Phase 5 — Live refresh + the rest of the game.** Folder watcher so the dashboard updates as runs finish; relic and potion analytics on the same metric framework.

## Setup

Requires Python 3.10+ and a Windows machine where you've launched Slay the Spire 2 at least once (so the run-history files are present locally). No third-party dependencies for Phase 1; everything uses the standard library.

```bash
git clone https://github.com/Liam-Loebl/sts2-stats.git
cd sts2-stats
python import_all.py
```

That's the whole setup. `import_all.py` auto-discovers your StS2 history folder, builds `sts2_stats.sqlite` next to the script, and ends with a sanity report. Re-run it any time; only new runs are ingested.

The `.run` JSON files themselves are not in this repo; they live in your local `%APPDATA%`.

## Stack

- **Python 3.12** (3.10+ supported): parser, importer, metric computation
- **SQLite** (standard-library `sqlite3`): storage, single file, no server
- **Streamlit**: dashboard (Phase 2+)
- **git**: version control

## Repo layout

```
sts2-stats/
├── import_all.py        one-command entrypoint
├── verify.py            invariant + cross-source checks (exit non-zero on failure)
├── sts2_stats/          the package
│   ├── paths.py         save-folder auto-detection
│   ├── parser.py        .run JSON -> normalized records
│   ├── db.py            SQLite schema + sanity report
│   └── importer.py      idempotent upsert
├── SPEC.md              full design doc
└── sts2_stats.sqlite    generated locally; not checked in
```

`SPEC.md` is the long-form design document: the metric definitions in full, the schema, the edge cases I hit while reverse-engineering the save format, and the open questions for later phases.
