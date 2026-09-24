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
