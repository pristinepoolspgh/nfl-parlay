#!/usr/bin/env python3
"""Team offensive efficiency from nflverse aggregates.

Usage:  python3 board/epa.py [season]     # default: current year

Pulls nflverse's regular-season team stats (built from play-by-play)
and prints each offense's EPA per game — passing, rushing, combined —
plus CPOE (completion % over expected), sorted best-first. EPA is the
"how good is this offense really" number the yards column hides.

Honest limits: this file carries OFFENSE only; defensive EPA lives in
the full play-by-play, which is far larger and not fetched here. Early
in a season these numbers are small samples — the playbook's rule
applies (under ~50 team plays of a type, treat as noise).
"""
import csv
import io
import subprocess
import sys
from datetime import datetime

URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "stats_team/stats_team_reg_{season}.csv")


def fetch(season):
    out = subprocess.run(["curl", "-sSgL", "--max-time", "30",
                          URL.format(season=season)],
                         capture_output=True, check=True)
    return list(csv.DictReader(io.StringIO(out.stdout.decode())))


def main():
    season = sys.argv[1] if len(sys.argv) > 1 else str(datetime.now().year)
    rows = fetch(season)
    table = []
    for r in rows:
        g = int(r.get("games") or 0)
        if not g:
            continue
        pe = float(r.get("passing_epa") or 0)
        re_ = float(r.get("rushing_epa") or 0)
        table.append({"team": r["team"], "g": g,
                      "pass_pg": pe / g, "rush_pg": re_ / g,
                      "off_pg": (pe + re_) / g,
                      "cpoe": float(r.get("passing_cpoe") or 0)})
    table.sort(key=lambda t: -t["off_pg"])
    print(f"{season} offense · EPA/game (nflverse, {table[0]['g'] if table else 0}+ games)")
    print(f"{'TEAM':<5}{'OFF':>7}{'PASS':>7}{'RUSH':>7}{'CPOE':>7}")
    for t in table:
        print(f"{t['team']:<5}{t['off_pg']:>7.2f}{t['pass_pg']:>7.2f}"
              f"{t['rush_pg']:>7.2f}{t['cpoe']:>7.1f}")


if __name__ == "__main__":
    main()
