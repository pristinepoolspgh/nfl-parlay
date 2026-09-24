#!/usr/bin/env python3
"""Do the sims' upset calls win? (Owner asked the board to let the sims
suggest upsets when they give the underdog a heavy chance.)

Usage:  python3 board/upset_test.py

Rule under test, fixed before running: the sims (v6: pure Elo, 4-pt
QB-change dock in weeks 5+) give the market's underdog at least T win
probability AND at least G more than the de-vigged closing line does.
Bet: $100 on that underdog's closing moneyline. Reported: count, the
dogs' real win rate vs what the market implied, and flat-stake ROI with
a bootstrap 95% CI. An ROI CI that stays below zero means "the market
already had it"; only a CI entirely above zero would be an edge.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tune

MARGIN_SD, DOCK = 13.2, 4.0


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def payout(ml):
    return ml / 100.0 if ml > 0 else 100.0 / -ml


def bets(rows, T, G):
    out = []
    for r in rows:
        if not (r.get("hml") and r.get("aml")):
            continue
        m = r["m"]
        if r["wk"] >= 5:
            m += (-DOCK if r["nh"] else 0) + (DOCK if r["na"] else 0)
        ph = phi(m / MARGIN_SD)
        pm = r["pm"]
        if pm >= 0.5:        # home favored -> dog is away
            p_dog_m, p_dog_s = 1 - pm, 1 - ph
            ml, won = r["aml"], r["actual"] < 0
        else:
            p_dog_m, p_dog_s = pm, ph
            ml, won = r["hml"], r["actual"] > 0
        if r["actual"] == 0:
            continue
        if p_dog_s >= T and p_dog_s - p_dog_m >= G:
            out.append((won, p_dog_m, float(ml)))
    return out


def summarize(b, label):
    if not b:
        print(f"  {label}: no games")
        return
    n = len(b)
    wins = sum(w for w, _, _ in b)
    implied = sum(p for _, p, _ in b) / n
    pnl = [payout(ml) if w else -1.0 for w, _, ml in b]
    roi = sum(pnl) / n
    rng = random.Random(7)
    boots = sorted(sum(rng.choice(pnl) for _ in range(n)) / n
                   for _ in range(4000))
    lo, hi = boots[100], boots[3899]
    print(f"  {label}: {n:4d} games  dogs won {wins/n*100:5.1f}% "
          f"(market implied {implied*100:5.1f}%)  ROI {roi*100:+6.1f}% "
          f"[{lo*100:+.1f}, {hi*100:+.1f}]")


def main():
    games = tune.load_games()
    rows = tune.replay(games, 20.0, 48.0)
    for name, sub in (("weeks 5+", [r for r in rows if r["wk"] >= 5]),
                      ("weeks 2+", rows)):
        print(f"\n{name}")
        for T, G in ((0.40, 0.08), (0.45, 0.10), (0.50, 0.10),
                     (0.50, 0.15), (0.55, 0.15)):
            summarize(bets(sub, T, G), f"sims ≥{T:.0%}, +{G*100:.0f} pts")
        summarize(bets(sub, 0.0, -1.0), "every underdog (baseline)")


if __name__ == "__main__":
    main()
