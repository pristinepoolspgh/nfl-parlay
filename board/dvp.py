#!/usr/bin/env python3
"""Defense vs position: what each defense allows to QBs, RBs, WRs, TEs.

Usage:  python3 board/dvp.py [season]      # table for one defense set
        python3 board/dvp.py --stability   # how much early weeks predict

Source: nflverse weekly player stats (stats_player_week_{season}.csv).
Per defense and position group, per game: PPR points, receptions,
receiving yards, and touchdowns (rushing + receiving; passing TDs for
QBs) allowed. Rank 1 = allows the MOST (softest matchup), 32 = fewest.
"""
import csv
import io
import os
import subprocess
import sys

PW_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
          "stats_player/stats_player_week_{season}.csv")
ALIAS = {"WAS": "WSH", "LA": "LAR", "JAC": "JAX", "SD": "LAC",
         "OAK": "LV", "STL": "LAR", "ARZ": "ARI"}
POS = ("QB", "RB", "WR", "TE")


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_rows(season):
    out = subprocess.run(["curl", "-sSgL", PW_URL.format(season=season)],
                         capture_output=True, text=True, timeout=120)
    if out.returncode or not out.stdout.startswith("player_id"):
        return []
    return [r for r in csv.DictReader(io.StringIO(out.stdout))
            if r.get("season_type") == "REG"]


def allowed(rows, weeks=None):
    """{def_team: {pos: {games, pts, rec, yds, td}}} per-game averages."""
    tot, games = {}, {}
    for r in rows:
        pos = r.get("position")
        if pos not in POS:
            continue
        wk = int(r["week"])
        if weeks and wk not in weeks:
            continue
        d = ALIAS.get(r["opponent_team"], r["opponent_team"])
        games.setdefault(d, set()).add(wk)
        t = tot.setdefault(d, {}).setdefault(
            pos, {"pts": 0.0, "rec": 0.0, "yds": 0.0, "td": 0.0})
        t["pts"] += _num(r["fantasy_points_ppr"])
        t["rec"] += _num(r["receptions"])
        if pos == "QB":
            t["yds"] += _num(r["passing_yards"])
            t["td"] += _num(r["passing_tds"])
        else:
            t["yds"] += _num(r["receiving_yards"]) + _num(r["rushing_yards"])
            t["td"] += _num(r["receiving_tds"]) + _num(r["rushing_tds"])
    out = {}
    for d, bypos in tot.items():
        n = len(games[d])
        out[d] = {p: {"g": n, **{k: round(v / n, 2) for k, v in s.items()}}
                  for p, s in bypos.items()}
    for p in POS:
        teams = sorted((d for d in out if p in out[d]),
                       key=lambda d: -out[d][p]["pts"])
        for i, d in enumerate(teams, 1):
            out[d][p]["rank"] = i
    return out


def spearman(a, b):
    keys = [k for k in a if k in b]
    ra = {k: i for i, k in enumerate(sorted(keys, key=lambda k: a[k]))}
    rb = {k: i for i, k in enumerate(sorted(keys, key=lambda k: b[k]))}
    n = len(keys)
    d2 = sum((ra[k] - rb[k]) ** 2 for k in keys)
    return 1 - 6 * d2 / (n * (n * n - 1))


def stability(seasons=(2022, 2023, 2024, 2025)):
    """Rank correlation between a defense's early-season points allowed
    to a position and what it allowed the rest of the season. 1.0 would
    mean the early table fully predicts; 0 means it's noise."""
    print("Spearman, early-window rank vs rest-of-season rank (PPR allowed)")
    print("season  window    " + "  ".join(f"{p:>5}" for p in POS))
    for s in seasons:
        rows = load_rows(s)
        if not rows:
            continue
        last = max(int(r["week"]) for r in rows)
        for label, early in (("wks 1-2", range(1, 3)),
                             ("wks 1-4", range(1, 5)),
                             ("wks 1-8", range(1, 9))):
            a = allowed(rows, set(early))
            b = allowed(rows, set(range(max(early) + 1, last + 1)))
            vals = []
            for p in POS:
                vals.append(spearman({d: a[d][p]["pts"] for d in a if p in a[d]},
                                     {d: b[d][p]["pts"] for d in b if p in b[d]}))
            print(f"{s}    {label}   " + "  ".join(f"{v:+.2f}" for v in vals))
        prev = allowed(load_rows(s - 1)) if s > 2022 else None
        if prev:
            cur = allowed(rows)
            vals = [spearman({d: prev[d][p]["pts"] for d in prev if p in prev[d]},
                             {d: cur[d][p]["pts"] for d in cur if p in cur[d]})
                    for p in POS]
            print(f"{s}    last yr    " + "  ".join(f"{v:+.2f}" for v in vals))


if __name__ == "__main__":
    if "--stability" in sys.argv:
        stability()
    else:
        season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
        t = allowed(load_rows(season))
        for p in POS:
            print(f"\n{p}  (rank 1 = allows the most)")
            for d in sorted(t, key=lambda d: t[d].get(p, {}).get("rank", 99)):
                s = t[d].get(p)
                if s:
                    print(f"  {s['rank']:2d} {d:4s} {s['pts']:5.1f} PPR/g  "
                          f"{s['rec']:4.1f} rec  {s['yds']:5.1f} yds  "
                          f"{s['td']:.2f} TD  ({s['g']} g)")
