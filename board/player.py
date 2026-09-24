#!/usr/bin/env python3
"""Look a player up on ESPN: career and recent-season numbers.

Usage:  python3 board/player.py "case keenum"

The point is judging players on their record instead of their name —
especially backups pressed into starts. A veteran QB with 80 games of
near-average efficiency is a different bet than a practice-squad
call-up, and the difference should be cited in numbers, not vibes.
Sources: ESPN's public search and athlete-stats APIs (keyless).
"""
import json
import subprocess
import sys
import urllib.parse

SEARCH = ("https://site.web.api.espn.com/apis/search/v2"
          "?query={q}&limit=5")
STATS = ("https://site.web.api.espn.com/apis/common/v3/sports/football/"
         "nfl/athletes/{aid}/stats")
SHOW = {"passing", "rushing", "receiving", "scoring"}


def curl_json(url):
    out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                         capture_output=True, check=True)
    return json.loads(out.stdout)


def find_athlete(query):
    d = curl_json(SEARCH.format(q=urllib.parse.quote(query)))
    for r in d.get("results", []):
        if r.get("type") != "player":
            continue
        for c in r.get("contents", []):
            uid = c.get("uid", "")
            if "~a:" in uid:
                return uid.split("~a:")[-1], c.get("displayName", query), c
    return None, None, None


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: player.py "player name"')
    query = " ".join(sys.argv[1:])
    aid, name, meta = find_athlete(query)
    if not aid:
        sys.exit(f"no ESPN player match for {query!r}")
    sub = (meta or {}).get("subtitle") or (meta or {}).get("description") or ""
    print(f"{name}" + (f"  ({sub})" if sub else "") + f"  espn:{aid}")
    d = curl_json(STATS.format(aid=aid))
    for cat in d.get("categories", []):
        if cat.get("name") not in SHOW:
            continue
        names = cat.get("names", [])
        rows = cat.get("statistics", [])
        if not rows and not cat.get("totals"):
            continue
        print(f"\n[{cat['name']}]")
        for row in rows[-3:]:
            season = (row.get("season") or {}).get("displayName", "?")
            pairs = ", ".join(f"{n}={v}" for n, v in
                              zip(names, row.get("stats", [])))
            print(f"  {season}: {pairs}")
        tot = cat.get("totals")
        if tot:
            pairs = ", ".join(f"{n}={v}" for n, v in zip(names, tot))
            print(f"  career: {pairs}")


if __name__ == "__main__":
    main()
