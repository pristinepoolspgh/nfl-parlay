# Disposition of the Sep 24 external review

Reviewer's verdict accepted: honest, well-instrumented, structurally
unable to find edge against FanDuel's own prices. Item-by-item status:

| # | Item | Status |
|---|------|--------|
| P6 | Residual-predictiveness regression | **DONE same day** — board/residual_test.py. Result: residuals carry zero information on sides (z≈0). Model relabeled as research on the board. |
| P4 | QB dock leakage check | **DONE (pre-review)** — no leakage (usual QB = strictly prior starts); but weeks 2–4 failed validation on extension, dock gated to wk5+ (sim v6). QB-value delta (dock = value(starter)−value(backup)) queued; validate on same 793 games. |
| P1 | Multi-book fair price | **Feasibility probed.** Reachable now: Bovada (already integrated in CLI), Kalshi (works with request pacing). Blocked from this egress: DraftKings, Fanatics, ESPN Bet (bot walls). The Odds API needs a key — owner can add ODDS_API_KEY to the environment secrets for DK/MGM/Caesars consensus at 500 req/mo. Build order: FD+Bovada+Kalshi median first, Odds API when keyed. |
| P3 | Edge-objective builders + EV display | Queued behind P1 (EV is zero by construction until a second price exists). Ticket EV line + eligibility threshold as specified. |
| P2 | Prop distributions + if-out tables | Queued (largest build). nflverse player-week has the inputs; negative-binomial/gamma per stat as specified; compare at every FD alt line. |
| P5 | Power/Shin de-vig; proportional TD-market hold removal | Queued; testable on the harness (affects ladder consistency more than headline probs). |
| P7 | SD = a + b·total; weather coefficient validation; market-seeded week-1 priors; tuning/live data split | Queued; all testable on the existing harness. games.csv carries total_line, roof, temp, wind for historical weather validation. |
| P8 | Ops | Crons are UTC-only on this platform (documented; DST retune scheduled for November). December Saturday window: to add. Feed-shape alert: to add to make_snapshot (fail loudly under 8 games in-season). Fractional-Kelly display: behind P1 (needs real edge). |
| — | Suppress 15-game calibration confidence | **DONE** — the book keeps the table for transparency but now states the sample is far below meaningful (~200 games). |
| — | "Safety" language on negative-EV tickets | Behind P1: EV vs FanDuel's own de-vig is zero by construction; language changes ship with the first real EV column. |

Standing rule unchanged: nothing ships without the paired-CI gate on
the harness, and market-facing claims now also require passing the
residual test on the affected market.
