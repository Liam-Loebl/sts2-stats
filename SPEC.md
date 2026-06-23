# Slay the Spire 2 — Personal Run Analytics App

## Spec / Build Brief (v2)

This document is the starting point for building the app. I wrote it so a developer (or
coding agent) with no prior context can pick it up. Read it fully before coding. v2 adds
a game-background section and confirmed data values from real run files.

---

## 1. What I'm building & why

A desktop app that ingests my own Slay the Spire 2 (StS2) run history and computes
performance analytics, focused on **per-card value metrics**. Inspired by streamer
Jorbs, who logs every run into a self-updating spreadsheet of per-card win rates and more.
His isn't public; this is my own version.

Goal is exploratory: *stats to look at and get ideas from*, since the game and my strategy keep
evolving. It is also a portfolio/learning project, so the reasoning behind the metrics matters
as much as a working result. Do not silently "simplify" the statistics below; I chose them
deliberately.

Scope: only my own single-player runs. Two machines (laptop + desktop), see §8.

---

## 2. Game background (so the metrics make sense)

StS2 is a roguelike deckbuilder, in Early Access since March 2026. Expect frequent
balance patches; cards get reworked often, which is why the per-card "reset on rebalance"
feature in §4 matters. Core loop: pick a character, climb through 3 acts, build a deck by
picking 1 card from a choice of options after most fights, fighting toward a boss each act.

- **Characters** (5 in EA, all played by the user):
  | ID | Name | Identity (for understanding card archetypes) |
  |---|---|---|
  | `CHARACTER.IRONCLAD` | The Ironclad | Strength/exhaust/self-damage, heals after combat (Burning Blood) |
  | `CHARACTER.SILENT` | The Silent | Low HP (70), poison/shivs/discard, draws extra (Ring of the Snake) |
  | `CHARACTER.NECROBINDER` | The Necrobinder | Summons a skeletal hand "Osty" companion, doom, ethereal NEW |
  | `CHARACTER.REGENT` | The Regent | "Stars" resource (banked energy), card creation, NEW |
  | `CHARACTER.DEFECT` | The Defect | Orbs (lightning/frost/etc.) and 0-cost cards |
  - The order above matches the in-game UI and the canonical `CHARACTERS` list in `app.py`. `theme.CHARACTER_RANGE` is paired positionally, so any new code keyed to this table will get the right per-character color.
  - Ascension is tracked independently per character. More characters/modes are on the EA roadmap, so never hardcode the roster; read it from the data.
- **Acts:** 3 acts per run in current Early Access. StS2 has a planned "Alternate Acts"
  system, but only Act 1 currently has a biome choice (Overgrowth *or* Underdocks). Acts 2
  and 3 each have a single biome for now (alternates still in development). An Act 4 / true
  ending / heart-style fight does not exist now but may be added later, so do not hardcode "3
  acts" anywhere; derive the act count from `map_point_history.length`. The act number is the
  position (1/2/3/...), which is the outer index of `map_point_history`. The biome name (in `acts`,
  e.g. `ACT.UNDERDOCKS`, `ACT.HIVE`, `ACT.GLORY`) currently only varies for Act 1, but treat it as a
  general dimension since Acts 2/3 will gain variants. Each act is ~17 floors, starts with an
  "Ancient" (choose 1 of 3 boons/relics) and ends with a boss. ~45–50 encounters per full run.
- **Map location types** (`map_point_type`): `monster`, `elite`, `boss`, `rest_site`,
  `shop`, `treasure`, `ancient`, `unknown` (event).
- **Card rewards:** after most combats you choose 1 of ~3 cards or Skip (shops offer more).
  This pick/skip choice is the heart of the WAR and Elo metrics.
- **Ascension (difficulty):** stacking modifiers, 1–10 in Early Access (cumulative, per
  character). May rise toward 20 at 1.0, so treat ascension as an adjustable numeric threshold;
  don't hardcode a max.
- **Co-op:** up to 4 players. Multiplayer runs exist in my history and must be excluded
  (see §3). Confirmed, not hypothetical.
- Cards can be upgraded (`current_upgrade_level`) and enchanted (`ENCHANTMENT.*`, a new
  StS2 mechanic). For v1, aggregate by base card id; the detail is preserved for later.

---

## 3. Data source (CONFIRMED — this is the foundation)

StS2 is a Godot / C# game. It writes one plain-JSON file per run, unencrypted.

**Location (Windows):**
```
%APPDATA%\SlayTheSpire2\steam\<steamid>\profile1\saves\history\<unix_start_time>.run
```
- Example shape:
  `C:\Users\<you>\AppData\Roaming\SlayTheSpire2\steam\<steamid>\profile1\saves\history\`
- Filename = run's unix start time, e.g. `1779397791.run`.
- Auto-detect by globbing `%APPDATA%\SlayTheSpire2\steam\*\profile*\saves\history`.
  Never hardcode the username or steamid; they differ per machine.
- Ignore `*.run.backup` (dupes, ~75 of them), `current_run.*.corrupt` (in-progress), `profile1/replays/*.mcr` (binary).
- **151 valid `.run` files** as of 2026-06-22 (98 solo + 53 co-op). Drifts as the user plays.

### Run JSON schema (schema_version 9, build `v0.105.1`)

Parser must tolerate schema/version changes across patches. Top-level fields:
- `win` (bool); `was_abandoned` (bool, = player quit, not a real loss).
- `ascension` (int); `build_id` (string, e.g. `"v0.105.1"`, used for per-card rebalance resets).
- `game_mode` (string). Confirmed values: `"standard"` (almost all runs) and `"custom"`. Filter to Standard.
- `seed` (string); `start_time` (unix int, the run's unique id); `run_time` (seconds).
- `acts` (array of biome names reached); `killed_by_encounter`; `killed_by_event`; `modifiers`;
  `platform_type`; `schema_version`.
- `players` (array). Length > 1 means multiplayer (co-op); store with `is_multiplayer` flag (default-filtered, toggleable, see §4). Each player has: `id` (int64, the player's 17-digit Steam ID), `character` (one of the 5 IDs above), final `deck` (cards: `id`, `current_upgrade_level?`, `enchantment?`, `floor_added_to_deck`), `relics`, `potions`, `max_potion_slot_count`. (`badges` is documented but empty/absent in observed co-op runs.)
- **Local user identification** (resolved): parse the local Steam ID once from the save-folder path
  (e.g. `.../steam/<steamid>/profile1/...` → `<steamid>`). In any run (solo or co-op),
  the local user is `players[i]` where `str(players[i].id) == local_steam_id`. Fallback: `players[0]`.
  100% of co-op runs in this dataset have the local user at index 0 (the save-writing client writes itself first).
  Important: `player_stats` arrays inside each map point are index-aligned with `players[]`, so once you
  resolve the local user's index `i`, use `player_stats[i]` for that user's per-room stats.
- `map_point_history`: array of acts → array of map points (rooms). Outer index = act number.
  Each map point: `map_point_type`, `rooms` (`model_id`, `monster_ids`, `room_type`, `turns_taken`),
  and `player_stats[]` (one entry per player, index-aligned with `players[]`).
- **Confirmed enum values** (full enumeration across all current run files):
  - `map_point_type` (8): `monster`, `elite`, `boss`, `rest_site`, `shop`, `treasure`, `ancient`, `unknown` (= event rooms).
  - `room_type` (7): `monster`, `elite`, `boss`, `rest_site`, `shop`, `treasure`, `event`. (Note: a `map_point_type:"ancient"` map point's room has `room_type:"event"`, e.g. `EVENT.NEOW`.)
  - 20 distinct `ENCHANTMENT.*` IDs (Adroit, Clone, Corrupted, Glam, Goopy, Imbued, Instinct, Momentum, Nimble, Perfect_Fit, Royally_Approved, Sharp, Slither, Souls_Power, Sown, Spiral, Steady, Swift, Tezcataras_Ember, Vigorous).
  - Reward sources (map_point_types where `card_choices` appear): `monster`, `elite`, `boss`, `shop`, `ancient`, `unknown` (event). Treasure rooms and rest sites do not yield card rewards.
  - Skippable card rewards (where Elo's Skip entity applies): combat `monster` / `elite` / `boss` card rewards (pick rates 62–88%). Non-skippable: `ancient_choice` (100% picked), `event_choices` (100%), `rest_site_choices` (100%), treasure `relic_choices` (100%). Shops are skippable but gold-constrained (~17.6% card-buy rate, ~41.8% relic-buy); down-weight or exclude from Elo as planned.
  - `schema_version` values present: 8 (57 runs) and 9 (93 runs). Parser must handle both. Older v8 may lack some fields; use defensive `.get()` with defaults.
- **Floor numbering** (resolved, cumulative across acts): there is no explicit `floor` field on rooms or map points. The only floor-bearing JSON key anywhere is `floor_added_to_deck` (on card and relic objects).
  - Derivation: for `map_point_history[A][M]` (both 0-indexed), `floor = sum(len(map_point_history[k]) for k in 0..A-1) + M + 1`. Equivalently, walk in order and number 1,2,3,…
  - Shortcut for card picks: the picked card's own `floor_added_to_deck` already equals this number; just read it directly. Same for `cards_gained`, `bought_relics`, `cards_removed`, and the final `players[].relics`/`deck` lists.
  - Acts vary in length per run (typically 17 / 16 / 15 = 48 floors total, but don't hardcode; always use array length).
  - Highest floor seen in this dataset: 47.
- **`modifiers` field:** universally empty (`[]`) in every run observed to date, including the single `"custom"` run. We have no schema example of a populated modifiers entry. Keep this as a known gap; parser should accept any array shape defensively.

`player_stats` (per room) key fields:
- `card_choices`: `[{ card: { id, current_upgrade_level?, props? }, was_picked: bool }]`,
  the pick/skip data: every option offered + which was taken.
- `relic_choices`: `[{ choice, was_picked }]`; `potion_choices`: `[{ choice, was_picked }]`.
- `cards_gained`, `cards_removed`, `cards_transformed`, `cards_enchanted`, `upgraded_cards`,
  `bought_relics`, `rest_site_choices` (e.g. `SMITH`/`HEAL`), `ancient_choice`, `event_choices`.
- `damage_taken` (int per room, sum per act / character); `current_hp`, `max_hp`,
  `current_gold`, gold_* fields, `hp_healed`.

IDs: cards `CARD.*`, relics `RELIC.*`, potions `POTION.*`, characters `CHARACTER.*`,
enchantments `ENCHANTMENT.*`.

---

## 4. Filters ("what counts as a run")

Every stat passes through these. Defaults below; all are adjustable in the UI.
Filter at query time, never delete runs (reversible; lets us compare later).

| Filter | Default | Notes |
|---|---|---|
| Multiplayer (co-op) | solo only, with toggle | Store all runs; mark each with `is_multiplayer` + `num_players`. UI toggle: Solo only / Co-op only / Both (e.g. compare A10 solo vs A10 co-op). WAR & Elo computed *separately per mode* (co-op baselines ≠ solo baselines, different game). Detect via `players` length > 1. Local user identification (resolved): `players[i]` where `str(players[i].id) == local_steam_id` (Steam ID parsed from save-folder path). Fallback: `players[0]` (100% reliable in current dataset). Co-op runs = 53 of 150 (35%, a meaningful slice, not edge case). |
| `game_mode` | Standard only | exclude `"custom"` (and any future seeded/daily modes) |
| Abandoned (`was_abandoned`) | excluded (toggle) | quit ≠ loss; allow including via toggle |
| Ascension | show all, adjustable threshold (e.g. "≥ N") | I raise it as I climb; EA max is 10, may rise. Don't hardcode. |
| Card version window | per-card, default = all (now populated) | When a card is reworked, count its stats only from that `build_id` forward. Hand-maintained in `card_reworks.json` (card → valid-from version); do not auto-detect card text changes. |
| Minimum patch (game version) | all versions | Restrict every stat to runs whose `build_id` is at/after a chosen version — a run-level window that complements the per-card valid-from list. UI: a discrete `select_slider` over the versions present (build_id can't be range-compared lexically, so the sidebar resolves the cutoff to the set of qualifying build_ids). |

---

## 5. Metrics

Conventions for all metrics:
- Always display sample size (N) next to every rate. Non-negotiable.
- **Shrinkage** for small samples: pull low-N rates toward the relevant baseline (empirical Bayes /
  simple shrinkage) so a "3-for-3" card doesn't show a fake 100%. Gray out / de-emphasize very low N.
- Sliceable per character and, where noted, per act.

> Context: ~150 runs (~25–30 per character, fewer after filtering to high ascension). Per-card
> *win-rate* numbers will be noisy for a while; show N honestly and shrink. Per-card *Elo* (§5.4) is
> far more stable because it's per reward-event, not per run.

### 5.1 Pick rate
`picks / times_offered`. Captures niche cards (rarely offered, always taken).

### 5.2 Win rate when picked
Win rate of runs where the card was picked at least once. Intuitive but confounded; always with N.

### 5.3 WAR (Wins Above Replacement) — outcome metric

> WAR(card) is computed at the per-(card, floor) level, then aggregated for display.
> For each pick of card C on floor F by character X, the "expected win" contribution is
> my win rate among runs of character X that reached floor F (the
> **character-conditional, floor-conditional baseline**).
>
> **WAR(C) = (W − E) / N**, where
> - **W** = total wins across runs where C was picked,
> - **E** = Σ over picks of the (character × floor) baseline win rate at the floor where C was picked,
> - **N** = total picks of C.
>
> Equivalently, this is the pick-weighted average of per-floor lifts (win-rate-when-picked-on-F
> minus the floor baseline). Baseline is character-conditional (Defect cards compared to
> Defect floor-baselines, not global).

It is NOT the global win rate, and it is NOT a pick-vs-skip differential.

**Displayed aggregations** (what the UI shows):
- Overall WAR: all floors combined (the primary headline number per card).
- Per-act WAR: Act 1 / Act 2 / Act 3, each computed by restricting the W/E/N sums to picks on
  floors belonging to that act.
- Per-floor numbers themselves are not displayed as primary stats; they're the *mechanism*. (Per-card
  per-floor breakdowns can be a stretch view, with noise warnings.)

**Why floor-level conditioning:** a card only offered late only appears in runs that *survived* to
that floor, and reaching later floors already correlates with winning. Conditioning at the floor level
directly neutralizes that survivorship bias at the decision point itself. (Per-act conditioning
would be a cruder approximation; per-floor is the rigorous choice I explicitly asked for.)

**Reliability note:** per-(card × floor) cells will often have N = 0 or 1, which is fine, because we
don't display them. The aggregate's reliability depends on the card's total pick count N, not the
per-floor N. A card picked 20 times across 15 floors still has N = 20 for its WAR. Apply
shrinkage at the aggregate level (low-N cards pull toward 0 WAR) and always show N.

The data model already supports this; `floor` is stored on every card event (see §6).

### 5.4 Elo — preference / revealed-value metric (complements WAR)

Each card reward is a mini-tournament: the picked option "beats" the passed-over options. Skip is
a rated entity too. Standard Elo: `update = K × (result − expected)`, `expected` from the rating gap.
Beating a higher-rated option gains more; being passed over for a strong option loses little.

**Multi-option handling** (important; I explicitly raised this): rewards have 4+ options
(3 cards + skip; shops more), so most options lose each reward. Handle via **multi-way pairwise**:
the picked option plays a separate match against each other option, and the updates are summed:
- A pick = beating all N−1 alternatives, a large up-move; a pass = one loss, a small down-move.
- This makes "winning bigger than losing" structurally, scaled to option count (a 7-card shop
  pick beats 6), while staying zero-sum / non-inflating and keeping ratings interpretable.
- Do not implement the asymmetry as `K_win > K_loss` as the core mechanism (inflates ratings,
  breaks interpretability). Leave only as an optional tuning knob.

Other Elo decisions:
- Per-character pools (cards are character-specific); optionally per-act Elo.
- Model a Skip rating per character **and per act** (the skip line shifts by act): cards above it are "worth taking," below it "usually pass."
- Chronological Elo first (process oldest→newest, like Jorbs), which enables an Elo-over-time trend.
  A Bradley-Terry batch model (order-independent, statistically cleaner) is a later refinement.
- K-factor tunable.
- Shops are a noisy Elo signal (passing a card may be gold-constrained, not preference).
  Down-weight or exclude shop card rewards from Elo initially; combat/elite/boss rewards are clean.

### 5.4a Phase 3 scope decisions (locked, audit-driven)

Before any WAR / Elo code is written, two semantic decisions are locked
in here so they can't drift during implementation.

**`source_type` scope.** The default Phase 3 Card Rankings board includes
**only** these `card_events.source_type` values in both pick-rate, WAR,
and Elo math:
  - `monster` — standard 3-option combat reward, skippable
  - `elite` — elite combat reward, skippable
  - `boss` — boss combat reward, skippable
  - `ancient` — Ancient boon-style choice (forced pick of 1)

Excluded by default (toggleable in the UI later):
  - `shop` — the recorded "reward" is the full shop inventory across
    restocks, not a 3-option pick screen; empirically ~0.7% pick rate,
    so it poisons the Skip-as-entity Elo update by flooding every shop
    card with phantom losses to Skip. Shops can re-enter analysis later
    as a separate "purchase decision" pool conditioned on gold/price.
  - `unknown` — event rooms with 12–26 mixed options of unclear
    semantics. Until parser.py is extended to label these correctly,
    leave them out of WAR/Elo.

**Multi-pick rewards.** A handful of reward groups (~1% of the analysis
pool) have more than one `was_picked = true` — apparently a real game
mechanic (card-grab events) rather than a parser bug. The Elo "picked
beats every alternative" rule doesn't have an obvious answer for these.
Policy for v1: **exclude reward groups with `SUM(was_picked) > 1` from
the Elo pool**. They stay in WAR's "win-when-picked" aggregate (every
picked card still gets a contribution), but the Elo update skips them.
One-line filter. Revisit when there's more data.

**Implemented (Phase 3).** The engine is `sts2_stats/rankings.py`
(`compute_rankings(conn, filters, act=None)`) — the floor-conditional WAR
baseline, multi-way summed Elo with Skip as a per-character rated entity,
and the scope rules above. Tunable constants: WAR shrinkage `k = 10` phantom
replacement-level (lift-0) picks; win%-when-picked beta-binomial prior
strength `m = 10` toward the filtered win rate; Elo `K = 24`, initial 1500.
Correctness is pinned by an independent brute-force WAR recomputation (exact
match), an Elo zero-sum-per-character invariant, and a determinism check, all
wired into `verify.py`. The UI is the Card Rankings page
(`views/card_rankings.py`).

**Reward-size handling (investigated 2026-06-22).** The save stores every card
offered at a node in one flat `card_choices` list with **no** screen/reward
markers, so a node can list more cards than a single 3-card reward (relic
re-rolls / bonus rewards), and the oversized counts aren't multiples of 3 — they
can't be split back into screens. ~92% of combat rewards are the normal 3. The
Elo engine therefore (1) dedups repeated `card_id`s within a node (Elo-local),
(2) excludes multi-pick nodes (`SUM(was_picked) > 1`), and (3) excludes nodes
with more than `ELO_MAX_REWARD_CARDS` (= 5) distinct cards, since those are
aggregated multi-offers and treating them as one tournament would over-credit the
pick (~5% of in-scope groups, 82, dropped from Elo). WAR and pick% still count
every card offered. Skip is rated **per act** and exposed as a per-act Skip line
on the board (the skip line rises across acts). The clean long-term fix
(parser-side screen separation) stays deferred.

### 5.5 The headline insight: WAR vs Elo
WAR = what *wins*; Elo = what I *prefer*. The gap is the gold:
- High Elo + low WAR ⇒ overrated (I keep taking it; it doesn't win).
- Low Elo + high WAR ⇒ underrated (wins when taken; I usually pass).
Surface explicitly (an Elo-vs-WAR view / scatter).

### 5.6 Aggregate stats
- Overall + per-character win rate; win rate by ascension and over time.
- Damage taken per act and per character (sum `damage_taken` over an act's rooms).
- Floors/acts reached; where I die most (`killed_by_encounter`).

### 5.7 Relics & potions
Reuse the same machinery. Relics fit pick/skip + WAR + Elo directly (boss/shop/chest/ancient
choices). Potions are more about usage than acquisition, so mostly descriptive. After cards (later phase).

---

## 6. Architecture

```
.run files  →  Parser  →  SQLite DB  →  Dashboard (local web app, opens in browser)
   ↑                                          ↑
   └──────  Watcher (fires on new run)  ───────┘
```

- **Parser**: read each `.run`, apply filters, flatten into tables.
  - Must handle `schema_version` 8 and 9 (both present in current data) using defensive `.get()` with defaults. Quarantine truly unparseable runs to a log rather than failing the whole import.
  - Resolve the local user index once per file: `i` such that `str(players[i].id) == local_steam_id` (fallback `players[0]`). All per-user stats use `player_stats[i]` (index-aligned with `players[]`).
  - Floor on every event: walk `map_point_history` and assign cumulative floor 1, 2, 3, … to each map point. The picked card's `floor_added_to_deck` already equals this value; the parser computes the floor positionally (so non-pick options in the same reward get a floor too) and `verify.py` uses `floor_added_to_deck` as a cross-check.
- **SQLite** (one local file). Suggested tables:
  - `runs` (run_id [= start_time], character, ascension, build_id, game_mode, win, abandoned,
    `is_multiplayer`, `num_players`, run_time, acts_reached, killed_by, …). For co-op runs,
    `character` = the local user's character (identification mechanism TBD via data recon).
  - `card_events` (run_id, act_index, floor, `reward_event_id`, source_type [monster/elite/boss/
    shop/ancient/unknown], card_id, was_picked): one row per option per reward.
  - `reward_event_id` (or the tuple run_id + act + floor/map-index) must group all options of a
    single reward so Elo can reconstruct each choice set. Skip = a reward group with no
    `was_picked = true` AMONG the source_types that support skip — see Phase 3 design policy
    in §5 for which source_types are in the Elo pool.
  - `room_events` (run_id, act_index, map_point_index, floor, map_point_type, room_type,
    encounter_model_id, damage_taken, hp_healed, current_hp, max_hp, gold_gained, gold_spent,
    turns_taken): one row per room the local player passed through. Powers per-act damage
    stats (Phase 2) and any future replay/timeline views.
  - `import_log` (id, source_file, error, logged_at): quarantine for runs the parser couldn't
    read. Currently empty; helps a future schema change land softly instead of crashing the import.
  - Analogous tables for relic / potion choice events come later (Phase 5).
- **Idempotent import**, keyed on `start_time`/`seed`. Re-scanning never duplicates. The DB is
  disposable, fully rebuildable from the `.run` files.
- **Watcher**: background process (e.g. Python `watchdog`) on the history folder. On a new `.run`,
  parse + upsert, so stats update after every run.
- **Dashboard**: local web app opened in the browser.

**Stack:** Python + SQLite (stdlib) + dashboard framework + file watcher. Recommended start:
Streamlit (least code, good charts via Plotly, opens like an app) for ship-fast. I'm a
newer programmer with some Python, building via a coding agent.

---

## 7. UI / screens

Priority order (build top-down):
1. **Overview dashboard**: total runs, overall win rate, 5 character tiles (win rate + run count;
   names pulled live from data), win-rate-over-time, damage-per-act.
2. **Card rankings board**: sortable table of all cards with pick% · win% · WAR · Elo · N. Filter by
   character / act. Green→red WAR coloring. Low-N rows grayed. Click opens a detail page.
3. **Per-card / per-character detail pages**:
   - per-card: act splits, WAR by act, Elo-over-time, Elo-vs-WAR, pick/win rates.
   - per-character: win rate, damage curves per act, that character's best/worst cards.

Parked for later: a run-by-run timeline browser (replay a run's picks/skips/deck/map as data).

**Multi-page restructure (done, Phase 3):** the app is now a Streamlit multipage app via `st.navigation`. `app.py` is the router + shared chrome (theme, sidebar filters, import-on-load); each view under `views/` renders one page (Overview, Card Rankings), and shared helpers live in `dashboard_common.py`. The Phase 4 per-card / per-character detail pages slot in as additional views.

**Aesthetic:** lean thematic (StS2-flavored: dark, gritty), but refine the look after there's
a working build to react to. Start functional + themeable; escalate to a more custom UI only if I want it.

Stretch / "wow" (not committed): actual StS2 card art on tiles (assets in packed Godot files,
extraction effort unknown); pick-rate-vs-win-rate scatter.

---

## 8. Multi-machine

I play on both a laptop and a desktop. Steam Cloud syncs the `.run` files to both, so each
has the full history locally.
- Auto-detect the save path (glob); never hardcode user/steamid.
- Idempotent import keyed on run id, so each machine builds its own local DB from its synced files;
  both DBs converge to identical stats.
- DB is local + rebuildable per machine. Do not sync the SQLite DB itself via OneDrive/Dropbox
  (cloud-sync can corrupt a live DB).
- **Freshness caveat:** runs from the *other* machine appear only after Steam Cloud syncs them down
  (on the next StS2 launch there). The watcher catches *local* runs instantly.

---

## 9. Build order (each phase usable on its own)

1. **Foundation** (done): parser + SQLite schema (incl. `reward_event_id` grouping) + import all current runs.
   Then sanity-check together: total runs, win rate, runs per character, multiplayer/custom counts.
2. **Overview dashboard** (done): first thing to open and react to.
3. **Card rankings board** (done): pick%, win%, WAR, Elo (sortable; N shown; shrinkage; coloring).
4. **Per-card / per-character detail pages** (done): `views/card_detail.py` + `views/character_detail.py`, reachable from the nav and from "Detail →" buttons on the board / Overview.
5. **Auto-update watcher.**
6. **Relics / potions + polish + stretch features.**

---

## 10. Non-negotiable principles (don't let these get lost)

- **Run files are the single source of truth.** DB is derived and rebuildable; nothing deleted; filters
  applied at query time.
- **Show N everywhere and shrink low samples.** Never present a raw small-sample rate as fact.
- **WAR baseline is character + floor conditional**, aggregated to overall and per-act for display.
  Not global, not pick-vs-skip, not act-only. This controls for survivorship bias at the decision
  point, which is the whole point.
- **Elo is multi-way pairwise** (pick beats all alternatives incl. skip), summed, zero-sum. Don't fake
  the win/loss asymmetry with K-factors.
- **Auto-detect paths**; idempotent import; portable across both machines.
- **Never hardcode** the roster, ascension max, number of acts, or schema. Read from data; tolerate patch changes. (Act 4 / Heart may be added; new characters are on the roadmap.)
- **Co-op runs are stored, not discarded.** Default filter is solo only; toggle in UI for co-op-only or both. Compute metric baselines per mode separately.
- **Card display names**: prettify IDs (`CARD.HELIX_DRILL` → "Helix Drill") with a hand-maintained JSON overrides file for cases where the auto-result is ugly. Same approach for relics/potions/characters.
- **Card-rebalance "valid-from" list** (`card_reworks.json`, repo root): a hand-maintained JSON map of `card_id` → minimum `build_id` its current form is valid from; earlier events are excluded so each card shows only its latest version. Cards not listed use all their data. Underscore-prefixed keys are notes and ignored. Implemented in `sts2_stats/reworks.py`, applied in `sts2_stats/rankings.py`; sourced from Jorbs' StS2 CardStats version-era ranges, not auto-detected.
- **Version control from day one**: Git + GitHub. `.gitignore` excludes raw `.run` files, the SQLite DB, and any local config holding personal data.
- This is a learning + portfolio project. Preserve the statistical intent; don't dumb metrics down.
