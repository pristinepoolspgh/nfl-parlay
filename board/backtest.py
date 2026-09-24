#!/usr/bin/env python3
"""Backtest the sim's margin model on real seasons.

Usage:  python3 board/backtest.py

Replays 2025 and 2026-to-date game by game. Every prediction uses only
what was knowable before kickoff: Elo ratings built from prior finals,
and nflverse EPA from prior weeks of the same season. Grades winner
accuracy, margin MAE, and Brier score for a grid of EPA blend weights
(w = n/(n+K); smaller K trusts EPA sooner), plus pure Elo and pure
EPA. Whatever wins here is what the live model should run — and if
pure Elo wins, the blend deserves to die.

Warm-up: predictions start week 5 of 2025 (Elo needs footing) and
week 2 of 2026. Playoffs update ratings but are not scored (neutral
sites, rest asymmetries). Where our own logged market lines overlap
(2026 week 2 favorites in memory/results.jsonl), the market's Brier
is printed beside the models' on those same games.
"""
import csv
import io
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elo

MARGIN_SD = 13.2
GRID = [None, 12.0, 8.0, 6.0, 4.0, 2.0, 0.0]  # None = pure Elo, 0 = pure EPA


def label(k):
    return "pure Elo" if k is None else "pure EPA" if k == 0 else f"K={k:g}"


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def epa_by_week(season):
    """{team: sorted [(week, epa_for, epa_against)]} from nflverse."""
    out = subprocess.run(["curl", "-sSgL", "--max-time", "30",
                          elo.EPA_URL.format(season=season)],
                         capture_output=True, check=True)
    rows = list(csv.DictReader(io.StringIO(out.stdout.decode())))
    alias = {"WAS": "WSH", "LA": "LAR", "JAC": "JAX", "ARZ": "ARI"}
    per_game = {}  # (team, week) -> epa
    opp = {}       # (team, week) -> opponent
    for r in rows:
        if r.get("season_type") != "REG":
            continue
        try:
            e = (float(r.get("passing_epa") or 0)
                 + float(r.get("rushing_epa") or 0))
            w = int(r["week"])
        except (ValueError, KeyError):
            continue
        t = alias.get(r["team"], r["team"])
        o = alias.get(r.get("opponent_team", ""), r.get("opponent_team", ""))
        per_game[(t, w)] = per_game.get((t, w), 0.0) + e
        opp[(t, w)] = o

    def upto(team, week):
        """Off/def EPA per game from weeks strictly before `week`."""
        offs, defs = [], []
        for (t, w), e in per_game.items():
            if w >= week:
                continue
            if t == team:
                offs.append(e)
            elif opp.get((t, w)) == team:
                defs.append(e)
        if not offs:
            return None
        return {"off": sum(offs) / len(offs),
                "def": sum(defs) / len(defs) if defs else 0.0,
                "n": len(offs)}
    return upto


def margin_pred(ratings, g, epa_fn, week, k):
    ra = ratings.get(g["home"], 1500.0) + (0.0 if g["neutral"] else elo.HFA)
    rb = ratings.get(g["away"], 1500.0)
    m_elo = (ra - rb) / 25.0
    if k is None:
        return m_elo
    eh = epa_fn(g["home"], week)
    ea = epa_fn(g["away"], week)
    if not eh or not ea:
        return m_elo
    hfa_pts = 0.0 if g["neutral"] else elo.HFA / 25.0
    m_epa = (eh["off"] - ea["off"]) + (ea["def"] - eh["def"]) + hfa_pts
    if k == 0:
        return m_epa
    n = min(eh["n"], ea["n"])
    w = n / (n + k)
    return (1.0 - w) * m_elo + w * m_epa


def main():
    preds = {k: [] for k in GRID}   # (pred_margin, actual_margin)
    y26 = {k: [] for k in GRID}
    wk2 = {}                        # frozenset(teams) -> {k: p_home}, home
    ratings = {}

    for season, start_pred in ((2025, 5), (2026, 2)):
        epa_fn = epa_by_week(season)
        for w in range(1, 19):
            games = elo.fetch_week(season, 2, w)
            if not games:
                break
            for g in games:
                if w >= start_pred and g["hs"] != g["as"]:
                    actual = g["hs"] - g["as"]
                    for k in GRID:
                        m = margin_pred(ratings, g, epa_fn, w, k)
                        preds[k].append((m, actual))
                        if season == 2026:
                            y26[k].append((m, actual))
                    if season == 2026 and w == 2:
                        wk2[frozenset((g["home"], g["away"]))] = {
                            "home": g["home"],
                            "p": {k: _phi(margin_pred(
                                ratings, g, epa_fn, w, k) / MARGIN_SD)
                                for k in GRID},
                            "won_home": g["hs"] > g["as"]}
                elo.update(ratings, g)
        if season == 2025:
            for st3w in range(1, 6):
                for g in elo.fetch_week(2025, 3, st3w):
                    elo.update(ratings, g)
            for t in ratings:
                ratings[t] = 1500.0 + (ratings[t] - 1500.0) * (
                    1 - elo.SEASON_REGRESS)

    def report(name, rows_by_k):
        print(f"\n{name} ({len(rows_by_k[None])} games)")
        print(f"{'model':<10}{'winner%':>9}{'MAE':>7}{'Brier':>8}")
        for k in GRID:
            rows = rows_by_k[k]
            if not rows:
                continue
            acc = sum((m > 0) == (a > 0) for m, a in rows) / len(rows)
            mae = sum(abs(m - a) for m, a in rows) / len(rows)
            brier = sum((_phi(m / MARGIN_SD) - (1.0 if a > 0 else 0.0)) ** 2
                        for m, a in rows) / len(rows)
            print(f"{label(k):<10}{acc*100:>8.1f}%{mae:>7.2f}{brier:>8.4f}")

    report("2025 wk5+ & 2026 wk2+", preds)
    report("2026 only (wk2+)", y26)

    # Market comparison on our logged 2026 week-2 favorites.
    res_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "memory", "results.jsonl")
    if os.path.exists(res_path):
        joined = []
        for line in open(res_path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            away, home = r["matchup"].split(" @ ")
            g = wk2.get(frozenset((home, away)))
            if not g:
                continue
            mkt_p_fav = r["p_fav"]
            fav_won = r["fav_won"]
            joined.append((mkt_p_fav, fav_won, g, r["fav"], home))
        if joined:
            print(f"\nvs market, 2026 wk2 favorites ({len(joined)} games)")
            mb = sum((p - (1.0 if wn else 0.0)) ** 2
                     for p, wn, *_ in joined) / len(joined)
            print(f"{'market':<10}{'':>9}{'':>7}{mb:>8.4f}")
            for k in GRID:
                b = 0.0
                for _, _, g, fav, home in joined:
                    p_fav = g["p"][k] if fav == home else 1.0 - g["p"][k]
                    won = g["won_home"] if fav == home else not g["won_home"]
                    b += (p_fav - (1.0 if won else 0.0)) ** 2
                print(f"{label(k):<10}{'':>9}{'':>7}{b/len(joined):>8.4f}")


if __name__ == "__main__":
    main()
