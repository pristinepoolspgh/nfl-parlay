# Backtest log

Reproduce any entry with `python3 board/backtest.py` (predictions use
only pre-kickoff information; warm-up weeks excluded).

## 2026-09-24 — EPA blend evaluation (led to sim v4)

224 scored games (2025 wk5+, 2026 wk2+). w = n/(n+K); smaller K
trusts EPA sooner. The live model at the time ran K=6.

| model    | winner% | margin MAE | Brier  |
|----------|---------|-----------|--------|
| pure Elo | 63.8%   | 10.43     | .2245  |
| K=12     | 64.7%   | 10.54     | .2247  |
| K=8      | 64.3%   | 10.64     | .2261  |
| K=6      | 62.5%   | 10.73     | .2275  |
| K=4      | 62.5%   | 10.90     | .2299  |
| K=2      | 62.1%   | 11.21     | .2351  |
| pure EPA | 61.2%   | 12.30     | .2516  |

2026-only (16 games): pure Elo .2362 Brier vs K=6 .2723 — the blend
was hurting most exactly where it was supposed to help (early season).

Market comparison, 2026 wk2 logged favorites (15 games, Brier):
market .2416 · pure Elo .2438 · K=6 .2815.

**Decision: cut the EPA blend (sim v4). Elo margins only, QB-out dock
and weather press kept.** K=12 wins winner% by 0.9pt but loses MAE
and Brier; calibration feeds the ticket math, so Brier decides.

## 2026-09-24 (second pass) — closing-line benchmark, 12 seasons

The first entry above was under-powered (224 games, no market
benchmark, raw EPA only) and its "decisive" framing was not earned.
This pass: 2,193 scored games (2015-2026 REG wk5+, Elo warmed from
2006, franchises unified), nflverse games.csv closing spread and
de-vigged moneyline as the benchmark, raw AND opponent-adjusted EPA
(6-round iterative), paired 95% CIs on Brier vs pure Elo.
Decision rule fixed in advance: a blend replaces Elo only if its CI
excludes zero in its favor.

| model        | winner% | MAE   | Brier  | ΔBrier vs Elo (95% CI) | vs market |
|--------------|---------|-------|--------|------------------------|-----------|
| CLOSING LINE | 67.6%   | 9.81  | .2084  | —                      | —         |
| pure Elo     | 64.7%   | 10.24 | .2204  | baseline               | +.0120    |
| raw K=12     | 65.1%   | 10.29 | .2204  | −.0000 ±.0027          | +.0120    |
| raw K=6      | 64.3%   | 10.44 | .2229  | +.0025 ±.0038          | +.0146    |
| raw K=3      | 63.7%   | 10.67 | .2263  | +.0059 ±.0047 (sig)    | +.0179    |
| adj K=12     | 64.5%   | 10.32 | .2213  | +.0009 ±.0028          | +.0129    |
| adj K=6      | 63.3%   | 10.50 | .2243  | +.0038 ±.0038          | +.0159    |
| adj K=3      | 63.2%   | 10.74 | .2282  | +.0077 ±.0048 (sig)    | +.0198    |
| pure adjEPA  | 62.3%   | 11.40 | .2375  | +.0171 ±.0064 (sig)    | +.0291    |

**Findings.** No blend qualifies: K=12 is a statistical dead heat,
everything heavier is worse, K=3 / pure EPA significantly so.
Opponent adjustment did not help (adds noise at in-season samples).
**sim v4 (pure Elo margins + QB-out dock + weather) stands.** The
market gap (+.0120 Brier) quantifies what scores can't see — the
ceiling the docks and the reads are attempting to recover; the live
per-version grading tests whether they do.

## 2026-09-24 (third pass) — parameter tuning and the QB-change dock

board/tune.py, same 2,193-game closing-line harness, greedy with
paired 95% CIs. Findings:
- MARGIN_SD 13.2, Elo K 20, HFA 48: already optimal (no variant
  significant).
- Rest-day differential: no coefficient helps — the market prices it.
- **QB-change dock: validated.** 793 games (2015-2026) where a team's
  listed starter differed from its season's most-used QB. Docks of
  1-4 pts all beat none; 4.0 optimal (Brier .2204 → .2175,
  Δ −.0029 ±.0023; dock=2 Δ −.0023 ±.0012). Closes a quarter of the
  gap to the closing line (.0120 → .0091).
**Adopted (sim v5):** dock stays 4.0 and now also fires when
FanDuel's prop-implied starter differs from the season's usual QB
(catches benchings and unlisted changes), not only on Out/Doubtful
injury listings. Constants unchanged.

## 2026-09-24 (fourth pass) — external review challenge: QB-dock leakage?

A reviewer asked whether the 793-game QB-dock validation leaked future
information ("season pass-attempt leader" computed over the full
season). **Answer: no leakage** — in board/tune.py the "usual" QB is
the modal starter over strictly PRIOR games (counter updates after
each prediction, min 3 prior starts); the wk5+ result reproduces
exactly (−.0029 ±.0023 at dock=4). The README's loose wording
described the live rule, not the backtest's; corrected.

**But the challenge exposed a real regime mismatch:** the live board
was docking week-3 games while the validation only covered changes
with ≥3 prior same-season starts (i.e., week 5+). Extending the test
to weeks 2–4 (250 changed-starter games, "usual" falling back to last
season's modal starter — still strictly pre-kickoff information):

| dock | Brier  | Δ vs none (95% CI) |
|------|--------|--------------------|
| 0    | .2306  | baseline           |
| 2    | .2313  | +.0007 ±.0027      |
| 4    | .2342  | +.0036 ±.0054      |
| 5    | .2363  | +.0057 ±.0066      |

Every early-week dock grades worse: September starter changes are
mostly planned switches, offseason moves, and returns the market has
already priced. **Adopted (sim v6): the dock is gated to week 5+.**
The four week-3 docks then on the live board (WSH, CHI, NYG, MIN)
were removed the same day.

## 2026-09-24 (fifth pass) — residual predictiveness (reviewer's P6)

board/residual_test.py: logistic regression of home-win outcome on
logit(closing prob) + [logit(model) − logit(closing prob)], sim v6
margins (dock in wk5+ only), same scored set.

| set | n | beta(residual) | z | LR stat |
|---|---|---|---|---|
| weeks 5+ (primary) | 2,193 | −0.001 ±0.118 | −0.01 | 0.00 |
| weeks 2+ | 2,728 | +0.043 ±0.107 | +0.40 | 0.16 |

**The model's disagreements with the closing line predict nothing on
game sides/totals.** Consistent with the dock finding: the dock made
the model less wrong, not informative beyond the market (which prices
QB changes harder than 4 pts). Consequences adopted: the board's
"Sims' calls" section now carries this result in its header; sim
disagreement is presented as research, not edge, until a non-FanDuel
fair price exists (multi-book consensus) and this same test passes on
some market. The test is rerunnable in one command and should gate
any future "the model sees value" claim.

## 2026-09-24 (sixth pass): do the sims' upset calls win?

Owner asked that the sims be allowed to suggest upsets when they give
the underdog a heavy chance. board/upset_test.py tests the rule before
it ships: sims (v6) give the market's underdog ≥T and ≥G more than the
de-vigged close; $100 on the dog's closing moneyline; bootstrap 95% CI
on ROI. Thresholds were fixed before the run.

| rule | weeks | n | dogs won | market implied | ROI [95% CI] |
|---|---|---|---|---|---|
| sims ≥50%, +10 pts | 2+ | 249 | 40.2% | 40.3% | −2.1% [−16.8, +12.3] |
| sims ≥50%, +10 pts | 5+ | 195 | 37.9% | 40.6% | −7.6% [−24.8, +9.3] |
| sims ≥45%, +10 pts | 2+ | 347 | 39.2% | 38.4% | +0.1% [−13.5, +13.8] |
| sims ≥50%, +15 pts | 2+ | 141 | 39.7% | 38.6% | +1.5% [−19.5, +23.0] |
| every underdog | 2+ | 2,728 | 33.5% | 33.6% | −4.4% [−9.8, +1.0] |

When the sims pick the upset, the dog wins about 4 in 10, which is
what the price already says, not the 50%+ the sims claim. No
threshold's CI clears zero. **Shipped as "Upset watch" with that
record printed under it** (rule: sims ≥50% and ≥10 pts over market,
excluding gaps an injured usual-starter QB explains). Calls are logged
on first sighting to memory/upsets.jsonl and graded by learn.py
(`upset_calls` in insights), so the live record accumulates next to
the backtest one.

## 2026-09-25 (seventh pass): is defense-vs-position signal or noise?

A friend asked for defense-vs-position (DvP) data. board/dvp.py builds
it from nflverse weekly player stats (PPR points, receptions, yards,
TDs allowed per game to QB/RB/WR/TE; rank 1 = allows the most). Before
showing it, `--stability` measured how well an early-season rank
predicts the same defense's rest of season (Spearman rank correlation,
1.0 = perfect, 0 = noise):

| window | QB | RB | WR | TE |
|---|---|---|---|---|
| weeks 1-2 (avg 2022-25) | .26 | .12 | .08 | .23 |
| weeks 1-8 (avg 2022-25) | .30 | .27 | .14 | .18 |
| last season (avg 2023-25) | .09 | .33 | −.03 | .19 |

DvP carries a little signal for QBs, TEs, and RBs and almost none for
WRs, and none of this is tested against prop prices (no historical prop
lines here). **Shipped as context only, not a model input:** each player
row shows this year's and last year's rank with games played, and the
props panel prints these correlations. Validating it against the
market needs archived prop lines, which the board has only just started
seeing.

## 2026-09-30 (eighth pass): market-anchored sims (v7)

Owner approved the plan: start the sims from the market's own number
and add only what beats it. board/market_model.py, games.csv closing
lines, fit on 2006-2018 (3,471 games), graded on 2019-2026 (2,008 games
never seen in fitting), paired bootstrap 95% CI, adopt only when the CI
excludes zero. Scoring = log loss on 22 alt lines per game (center
±0.5 to ±10.5), the job the sims actually do on the board.

| test | result | decision |
|---|---|---|
| margin shape: empirical key-number distribution vs normal sd 13.2 | −0.00261 [−0.00442, −0.00080] | **adopted** |
| total spread: normal sd 10 (old sims) vs fitted | old sd 10 worse by +0.00512 [+0.00293, +0.00729] | **sd = 10.0 + 0.08 × total adopted** (~13.7 at 46) |
| total shape: empirical kernel vs linear-sd normal | +0.00086 [−0.00043, +0.00218] | not adopted (no better) |
| weather beyond the closing total (train-bin shifts) | −0.00042 [−0.00204, +0.00133] | not adopted |
| Elo results rating blended into the closing spread (w = 0.08) | sq. error +0.146 [−0.152, +0.460] | not adopted |
| QB-change dock beyond the closing spread (793 games, wk5+) | 1 pt −1.08 [−2.73, +0.56]; 4 pts +6.11 [−0.45, +12.62] | not adopted |

What this means: the old sims' totals were overconfident. Real totals
land about 13.5 points from the closing total on average, not 10, so
every "Under 56.5 at 90%" the sims flagged last week was inflated by
the narrow curve. Nothing tested adds information on top of the
closing number itself, so v7 does not try to. It takes FanDuel's own
spread and total as the center and prices every rung with the
validated shapes. What v7 can still flag is internal inconsistency:
an alt rung, or the moneyline, priced off FanDuel's own main line.
First live read (week 4): the largest rung gap was under 5 points,
so "Sims' calls" is empty. The results rating (Elo, v6) stays on the
board labeled as research, still drives Upset watch with its own
graded record, and keeps being logged for grading (rr_* fields in
memory/simlog.jsonl). Week 4 carries both v6 and v7 rows for every
game, so learn.py grades the two versions side by side.
