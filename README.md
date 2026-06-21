# Slay the Spire 2 Stats

> A local-first stats tool for my Slay the Spire 2 runs — built to find which cards I overrate and which I should be picking more.

**Status:** Phase 1 (data ingest + storage) complete. Phase 2 (dashboard) in progress.

## The story

[Jorbs](https://www.twitch.tv/jorbs) is one of the best Slay the Spire players alive. A week or two after Slay the Spire 2 hit Steam Early Access in March 2026, he started keeping a private spreadsheet logging every run he plays — what character, what cards he picked, whether he won. He uses it to find the leaks in his own decisions: cards he keeps picking that don't actually win him games, cards he keeps skipping that would.

I've watched a lot of his streams. I wanted the same feedback loop for my own play — except I didn't want to fill in a spreadsheet by hand after every run. The game already writes a JSON file to disk every time a run ends. The data is right there. I just had to get it out.

So this project is two things at once. It's a tool I'm building because I actually want to use it to get better at the game. And it's the first real software project where I've had to make design decisions on my own — schema design, statistical methodology, edge cases I didn't anticipate — instead of following a tutorial.

## What's live right now (Phase 1)

- **Auto-detects the StS2 save folder** under `%APPDATA%` — same code works on my laptop and my desktop with no configuration.
- **Parses every `.run` JSON file** (~150 runs so far) and loads them into a local SQLite database.
- **Handles both schema versions** the game has shipped (v8 and v9 — the save format changed mid-Early-Access).
- **Co-op aware**: each co-op run is stored with a flag; the local player is identified by matching the Steam ID in the save-folder path against the player IDs inside the run.
- **Idempotent**: re-running the import is a no-op for runs already in the database.
- **Verified end-to-end** against the full corpus (150 runs, 9,882 card events) by four independent verification passes — zero discrepancies found.

The dashboard comes next.

## The interesting parts

Two problems were harder than I expected, and the solutions are what make the project worth talking about.

### Survivorship bias in card win rate

The naive way to measure a card is "win rate of runs that picked it." That number is misleading. Cards offered as a reward on Floor 45 are almost always in winning runs — because most losing runs are already dead by Floor 45. The card gets credit for the run surviving, not for helping it survive.

The fix is a metric called **WAR (Wins Above Replacement)**, borrowed from baseball sabermetrics. For each time I pick a card, the contribution is `(actual outcome) - (expected outcome)`, where the expected outcome is **my own win rate on that character among runs that reached that floor**. Pinning the baseline to the floor strips out the survivorship — so a Floor-45 card only earns positive WAR when picking it does better than the average run that had already gotten that far.

WAR is aggregated per-act and overall in the dashboard. Per-floor cells exist in the database but aren't surfaced — at 150 runs they're too noisy to be honest about.

### Measuring preference separately from outcome

WAR measures what wins. It doesn't measure what I *pick*. A card I love but skip half the time still won't show up as overrated in WAR.

So I'm also rating cards with **Elo**. Every card reward screen is a mini-tournament: the card I picked "beats" every alternative on offer, including Skip. The wrinkle: a standard Elo update is one-vs-one, but a reward screen has three or four options. I update pairwise across every (picked, alternative) pair and **sum** the updates. That structurally rewards picking against a wider field — beating three options is a stronger signal than beating one — without breaking Elo's zero-sum property (every point one card gains, another loses).

### Why the pair matters — the headline insight

WAR is an *outcome* metric. Elo is a *preference* metric. **The gap between them is where the learning lives:**

- **High Elo + low WAR** = a card I overrate. I keep picking it; it isn't winning me games.
- **Low Elo + high WAR** = a card I underrate. I usually skip it; when I take it, my runs do better.

Surfacing those two lists honestly, against my own play, is the whole point of the project — and the thing a generic tier list can't tell me.

## How it works

```
%APPDATA%/.../run-history/*.run    (Steam Cloud syncs these between machines)
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

- **Auto-detect, never hardcode.** No usernames or Steam IDs live in source. Each machine builds its own local DB from its own synced copy of the save files — no DB syncing, no cloud server.
- **Dual schema tolerance.** Both v8 and v9 save formats parse behind a single normalized representation, so the rest of the pipeline doesn't have to care which version wrote a given file.
- **Local user resolution in co-op.** The Steam ID is pulled from the save-folder path and matched against `players[i].id` inside each run. Falls back to `players[0]` only if no match — verified safe across all 53 of my co-op runs.
- **Verification scaffolding.** The same independent checks that audited Phase 1 stay in the repo, so when the game ships a v10 schema I can re-run them.

## Roadmap

- [x] **Phase 1 — Ingest.** Parser, SQLite schema, idempotent importer, sanity-report CLI.
- [ ] **Phase 2 — Overview dashboard.** Themed in-browser dashboard: total runs, per-character tiles, win-rate trends, damage per act.
- [ ] **Phase 3 — Card rankings board.** Pick%, win%, WAR, Elo — all sortable, sample size shown, shrinkage applied to low-N cards.
- [ ] **Phase 4 — Deep dives.** Per-card and per-character: WAR by act, Elo over time, Elo-vs-WAR scatter.
- [ ] **Phase 5 — Live refresh + the rest of the game.** Folder watcher so the dashboard updates as runs finish; relic and potion analytics on the same metric framework.

## Setup

Requires Python 3.10+ and a Windows machine where you've launched Slay the Spire 2 at least once (so Steam Cloud has synced your run history down). No third-party dependencies for Phase 1 — everything uses the standard library.

```bash
git clone https://github.com/Liam-Loebl/sts2-stats.git
cd sts2-stats
python import_all.py
```

That's the whole setup. `import_all.py` auto-discovers your StS2 history folder, builds `sts2_stats.sqlite` next to the script, and ends with a sanity report. Re-run it any time — only new runs are ingested.

The `.run` JSON files themselves are not in this repo; they live in your local `%APPDATA%` and are synced by Steam Cloud.

## Stack

- **Python 3.12** (3.10+ supported) — parser, importer, metric computation
- **SQLite** (standard-library `sqlite3`) — storage, single file, no server
- **Streamlit** — dashboard (Phase 2+)
- **git** — version control

## Repo layout

```
sts2-stats/
├── import_all.py        one-command entrypoint
├── sts2_stats/          the package
│   ├── paths.py         save-folder auto-detection
│   ├── parser.py        .run JSON -> normalized records
│   ├── db.py            SQLite schema + sanity report
│   └── importer.py      idempotent upsert
├── SPEC.md              full design doc (~400 lines)
└── sts2_stats.sqlite    generated locally; not checked in
```

`SPEC.md` is the long-form design document — the metric definitions in full, the schema, the edge cases I hit while reverse-engineering the save format, and the open questions for later phases.
