# Parlay Board — system handoff & audit guide

Personal NFL betting-analysis product for Jonathan Mehalic. This README is
written for a **reviewer doing a check-and-balance pass**: what exists, what
it claims, and how to verify every claim independently. Built Sep 20–24, 2026
by Claude (Claude Code session); everything below is reproducible from this
repo.

## The product, in one paragraph

A phone-first web board that pulls FanDuel's live NFL market, strips the vig
out of every price, runs its own graded prediction model on each game, and
builds parlays four ways (safest-N, safety-target, payout-goal, and
"Build my own", where any moneyline, spread, total, alt rung, prop or TD
scorer can be tapped onto a ticket)
— every ticket opening in the user's own FanDuel app via one-tap
`addToBetslip` links. It tracks saved tickets for multiple users, settles
them automatically, keeps a season memory of everything it predicted, and
grades itself weekly. Nothing here is betting advice, and the board says so.

## Where it runs

| Surface | URL | What it is |
|---|---|---|
| Full app | https://claude.ai/artifact/SuKFMDPsudMcWBdYktJ9sE | Board + tracker + crew standings + weekly read ("anyone with the link"; saving needs a Claude login) |
| Public mirror | https://nfl-parlay-inky.vercel.app | Static copy, no login, no tracker; redeploys automatically on every push to this repo (`web/index.html`, `vercel.json`). Installable to the Home Screen (`web/manifest.webmanifest`, icons, `web/sw.js`: network-first, last board offline). On open, on return to the app, and every 5 min it re-fetches itself and, if the board changed, shows what matters (finals, starters ruled Out/Doubtful, new QB docks, new upset calls, favorites flipping, prices moving 3+ pts); Refresh keeps the user's ticket. |
| Repo | github.com/pristinepoolspgh/nfl-parlay | Everything: code, ledgers, docs |
| Push alerts | Supabase project `parlay-board` (`phxacgxbhphnvrbcrbtr`), edge function `parlay-push` | Stores Home Screen app subscriptions and sends alerts; see "Push alerts" below |

## Components

```
nfl_parlay.py          CLI (slate, parlays, props, FanDuel one-tap links)
board/make_snapshot.py Board generator: fetches everything, runs the model,
                       writes the page + prediction/closing-line logs
board/template.html    The page (all UI logic; data spliced at /*__DATA__*/)
board/elo.py           Elo ratings from real finals (+ nflverse EPA fetch)
board/sim.py           The model ("sims"): margins, totals, win prob,
                       p_cover/p_over for any rung. VERSION history in header
board/backtest.py      12-season backtest vs the closing line
board/tune.py          Parameter experiments on the same harness
board/residual_test.py Does the model add information beyond the close?
board/upset_test.py    Do the sims' upset calls win? (Upset watch record)
board/dvp.py           Defense vs position tables + stability test
board/learn.py         Grades favorites, leans, sim log (per version), crew
board/settle.py        Grades saved tickets against ESPN finals
board/crew.py          Folds all users' tickets into the season ledgers
board/player.py        Any player's career/season numbers (ESPN APIs)
board/epa.py           Team offensive EPA/game table (nflverse)
memory/                Append-only ledgers (see "Ledgers")
docs/research-playbook.md  Owner-supplied research doctrine + repo mapping
docs/backtests.md      Every backtest run, tables, decisions taken
web/index.html         The mirror copy of the current board
```

## Data sources (all free/keyless; fetched via curl)

FanDuel public API (board, props, alt lines, TD scorers, in-play), ESPN
public APIs (scoreboard/week, injuries, news, athlete stats), NFL.com news
page, Rotowire NFL news feed, nflverse (`games.csv` incl. closing lines
1999→, weekly team/player stats), Open-Meteo (stadium weather). **Not
used:** any paid tool (OddsJam, PFF, etc.), X/Twitter (login/paid API;
Rotowire relays the same reporters with attribution), NFL Next Gen Stats
(requires auth).

## The model ("the sims") — version history

Full notes in `board/sim.py`'s header; evidence in `docs/backtests.md`.

- **v1** Elo margins (K=20, HFA=48, MOV multiplier, ⅓ season regression)
  + scoring-profile totals + 10k-draw modal scores.
- **v2** blended nflverse EPA into margins — **cut in v4**: a 2,193-game
  backtest vs the closing line (2015–2026) showed no blend weight beats
  pure Elo; heavier blends significantly worse.
- **v3** availability + weather enter the prediction: 4-pt dock when the
  starting QB is Out/Doubtful (starter = season pass-attempt leader per
  nflverse, so a hurt backup never triggers it); wind/rain press totals
  outdoors.
- **v4** EPA blend removed (see v2). SD 13.2 / K 20 / HFA 48 later
  re-confirmed optimal by grid search; rest days tested, add nothing.
- **v5** QB-change dock **validated**: 793 changed-starter games
  2015–2026, docks 1–4 pts all beat none with 95% CI excluding zero, 4.0
  optimal — closes a quarter of the model's gap to the closing line. Dock
  also fires when FanDuel's prop-implied starter differs from the
  usual QB (catches benchings the injury report never lists). Precision
  note: the backtest's "usual" QB is the modal starter over strictly
  prior games (no look-ahead); the live rule approximates it with the
  season-to-date pass-attempt leader.
- **v6 (current)** dock **gated to week 5+** after an external review
  challenged the validation. No leakage found, but re-testing weeks 2–4
  (250 changed-starter games) showed every dock size grades worse there
  — early changes are mostly planned and already priced. Full tables in
  `docs/backtests.md`.

**Upset watch:** games where the sims pick the underdog outright.
Backtest (249 games): the dogs won 40.2% vs 40.3% implied, so the
section prints that record and calls them live dogs, not locks.
Every game has a "player props" panel: all of FanDuel's main O/U props
and anytime-TD prices for every player, each tagged with what the
opposing defense allows to that position this year and last (context,
not a model input; see docs/backtests.md seventh pass).
Build-my-own allows one spread, one total, one ML side per game and one
side per prop (tapping another rung swaps it); TD scorers stack.

**Honest standing:** the closing line is better than the model
(Brier .2084 vs .2175 on the backtest). The board's "Sims' calls" section
says so in its header. The model's value is independence + the availability
layer, and its live record is graded per version so any regression shows.

## Money-math honesty rules (verify these first)

1. Every two-sided price is **de-vigged** (pair-normalized implied
   probabilities). One-sided markets (anytime TD) cannot be de-vigged and
   the section header says the vig is still in the number.
2. Displayed probabilities, payouts, and the safety/payout-goal guarantees
   are **pure market math**. The sims influence only *which* legs builders
   choose (market p penalized at half weight where the sims price a rung
   lower — never inflated by agreement).
3. Every model adjustment (QB dock, weather) is **disclosed on the game
   card** ("Already in the sims: …") so nobody double-counts it.
4. Payout tickets **prune drag legs** (≈ −2000 or shorter: ~zero payout,
   real risk) and say when the best build uses fewer legs than asked
   ("extra legs just feed the vig").
5. No invented stats: news is quoted as reported with the source's wording;
   player claims come from `board/player.py` lookups; roster questions
   defer to the live market over anyone's memory.
6. Parlay math treats legs as independent; FanDuel reprices same-game
   combos on the slip, and the board tells users to check the slip price
   before firing.

## Ledgers & self-grading (`memory/`)

- `pregame.jsonl` / `close.jsonl` — first-seen and latest pregame line per
  game (open-vs-close movement; closing-line value for leans).
- `simlog.jsonl` — every model prediction, logged pregame, **version-
  tagged**; `learn.py` grades winner accuracy / margin MAE / Brier per
  version, so model upgrades must beat their predecessors on the same
  scoreboard.
- `results.jsonl` + `insights.json` — market calibration by probability
  bucket, upsets, crew section. Week 2: market said 68.8%, favorites won
  66.7% (15 games).
- `judgments.jsonl` — the weekly "read": notes + at most 1–2 gradeable
  leans, never edited after the fact (material news appends dated notes).
  Record so far: 1–2.
- `upsets.jsonl`: every "Upset watch" call (sims ≥50% on the dog and
  ≥10 pts over market), first sighting, graded by `learn.py`.
- `tickets.jsonl` / `picks.jsonl` — every user's saved tickets and legs,
  kept even if deleted from the board; feeds crew standings/calibration.

## Automation (Routines bound to the building session)

| When (ET) | What |
|---|---|
| Tue 9:00a | Grade last week (incl. CLV review), settle, roll board to new week |
| Thu/Mon 7:00p | Refresh + optional 1-lean read (after inactives) |
| Sun 11a, **12p**, 1p, 3p, 5p, 7p | Refresh, weekly read (≤2 leans), live prices, settle; the noon run exists to re-check 11:30a inactives |

Every cycle publishes the artifact **and** pushes `web/index.html`, which
redeploys the mirror. Routine prompts point at `board/sim.py`'s header and
`docs/` rather than hardcoding model claims.

## Push alerts

Home Screen app users (iPhone: iOS 16.4+, installed from Safari) can tap
**Turn on alerts**. Pieces:

- `supabase/functions/parlay-push/`: `webpush.ts` (VAPID + aes128gcm
  encryption on WebCrypto, checked against the `http_ece` reference
  decryptor), `diff.ts` (what counts as alert-worthy), `index.ts`
  (subscribe / unsubscribe / test / check).
- Supabase project `parlay-board` (free plan, separate from the
  business's `pristine-tracker`): tables `push_subs`, `push_keys` (VAPID
  pair, generated server-side on first use), `push_state` (last board
  seen), `push_log` (every alert sent, with counts). RLS on, no
  policies: only the function's service role can read them.
- `pg_cron` job `parlay-push-check` posts `{"action":"check"}` every 10
  minutes. The function fetches the public board; if its `generated`
  stamp changed, it diffs against the last one and alerts only on:
  a QB newly Out/Doubtful, another player newly Out/Doubtful whose TD
  price was 30%+, a new sims QB dock, a new upset call, a flipped
  favorite, a 5+ point moneyline move, or a new week's board. Each
  Out/Doubtful alerts once per week. Quiet 11 PM-8 AM ET (changes wait
  until 8 AM).
- Dead subscriptions (404/410 from the push service, or 5 failures in a
  row) are deleted automatically.

Check it: `select * from push_log order by at desc` and
`select count(*) from push_subs` in that project.

## Access model

Artifact db rules: any signed-in viewer reads everything and writes only
their own tickets (owner-tagged; each user sees "My tickets" vs "Friends'
tickets"); only the owner/automation writes the model docs (`meta/*`) —
verified by a simulated lower-privilege write being refused. The Vercel
mirror is public read-only by design.

## How to verify the big claims

```bash
python3 board/backtest.py   # 12-season table vs closing line (~2 min)
python3 board/tune.py       # SD/K/HFA grids, rest, QB-dock validation
python3 board/elo.py        # ratings + model-vs-market edges
python3 board/sim.py        # today's projections vs market
python3 board/player.py "case keenum"
```
- De-vig spot check: any game's two prices → implied probs → normalize to
  100%; compare the board's numbers.
- One-tap check: tap a price, "Bet this ticket on FanDuel" must open the
  FanDuel app with those exact selections (price shown there governs).
- Ledger append-only check: `git log -p memory/judgments.jsonl` — leans
  never edited after grading, only dated notes appended.

## Known limitations (reviewer should know)

- The model trails the closing line (~.009 Brier) — expected; the line
  contains information scores can't. Treat "Sims' calls" as graded
  opinions, not edges proven profitable. CLV tracking exists to test that.
- Anytime-TD probabilities carry FanDuel's vig (disclosed on the board).
- Name matching across feeds (FD ↔ ESPN ↔ nflverse) is normalized but a
  mismatch would mis-tag an injury or mis-fire a dock; docks are disclosed
  per game so they're auditable at a glance.
- FanDuel/ESPN APIs are unofficial and can change shape (happened once;
  parser was fixed same-day).
- Routine times are UTC crons: US DST shift in November moves them an hour
  earlier ET until retuned. Saturday December slates have no firing window.
- No bankroll management is built in. High-variance products; the footer
  says "nothing here is betting advice" and means it.
- 2026 rosters postdate the builder's training data; all player-team facts
  come from live feeds, not memory.

## Prior CLI (original scope)

`nfl_parlay.py` remains a standalone, dependency-free CLI, superseded by
the board for daily use:

```
python3 nfl_parlay.py slate                  # today's games + win probs
python3 nfl_parlay.py parlay --legs 4        # safest parlay, fair-payout math
python3 nfl_parlay.py parlay --target 0.90   # aim for 90% combined
python3 nfl_parlay.py parlay --pay 500       # most likely +500 ticket
python3 nfl_parlay.py props DEN              # priced player props (--alts, --type)
python3 nfl_parlay.py slate --demo           # offline sample data
```
