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
