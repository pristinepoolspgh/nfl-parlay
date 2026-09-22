#!/usr/bin/env python3
"""The board's own prediction engine: Elo power ratings from real
game results.

Usage:  python3 board/elo.py            # rebuild ratings, show edges
        python3 board/elo.py --quiet    # rebuild, write memory/elo.json

Method (FiveThirtyEight-style):
- every team starts at 1500; ratings update after each final with
  K=20 scaled by a margin-of-victory multiplier that discounts
  blowouts by already-better teams;
- home field is worth 48 Elo points (~57% at even ratings), skipped
  for neutral-site games;
- between seasons every rating regresses one third toward 1500;
- win probability for a matchup is the logistic Elo formula.

The model is independent of betting markets by construction — it
sees only scores. Where it disagrees with the de-vigged market by
several points, that disagreement is a candidate lean, not a
verdict: the closing market is a strong opponent, and the ledger
in memory/ grades every claim either way.
"""
import json
import math
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import nfl_parlay as np

ELO_PATH = os.path.join(BASE, "memory", "elo.json")
K = 20.0
HFA = 48.0
SEASON_REGRESS = 1 / 3
TEAMS = set(np.STADIUMS_TEAMS) if hasattr(np, "STADIUMS_TEAMS") else None


def curl_json(url):
    out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                         capture_output=True, check=True)
    return json.loads(out.stdout)


np._get_json = curl_json


def fetch_week(year, seasontype, week):
    url = (f"{np.ESPN_URL}?dates={year}&seasontype={seasontype}"
           f"&week={week}")
    games = []
    try:
        payload = curl_json(url)
    except Exception:
        return games
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("state") != "post":
            continue
        t = {c["homeAway"]: c for c in comp.get("competitors", [])}
        home = t.get("home", {}).get("team", {}).get("abbreviation")
        away = t.get("away", {}).get("team", {}).get("abbreviation")
        if not home or not away:
            continue
        if home in ("AFC", "NFC") or away in ("AFC", "NFC"):
            continue  # Pro Bowl
        games.append({
            "home": home, "away": away,
            "hs": int(t["home"].get("score", 0)),
            "as": int(t["away"].get("score", 0)),
            "neutral": bool(comp.get("neutralSite"))})
    return games


def expected(ra, rb):
    return 1.0 / (1.0 + 10 ** (-(ra - rb) / 400.0))


def update(ratings, g):
    ra = ratings.setdefault(g["home"], 1500.0)
    rb = ratings.setdefault(g["away"], 1500.0)
    hfa = 0.0 if g["neutral"] else HFA
    exp_home = expected(ra + hfa, rb)
    if g["hs"] == g["as"]:
        actual = 0.5
    else:
        actual = 1.0 if g["hs"] > g["as"] else 0.0
    margin = abs(g["hs"] - g["as"]) or 1
    winner_diff = (ra + hfa - rb) if g["hs"] >= g["as"] else (rb - ra - hfa)
    mov = math.log(margin + 1) * (2.2 / (winner_diff * 0.001 + 2.2))
    delta = K * mov * (actual - exp_home)
    ratings[g["home"]] = ra + delta
    ratings[g["away"]] = rb - delta


def build():
    ratings = {}
    n = 0
    # 2025: full regular season and playoffs.
    for st, weeks in ((2, range(1, 19)), (3, range(1, 6))):
        for w in weeks:
            for g in fetch_week(2025, st, w):
                update(ratings, g)
                n += 1
    # Off-season regression toward the mean.
    for t in ratings:
        ratings[t] = 1500.0 + (ratings[t] - 1500.0) * (1 - SEASON_REGRESS)
    # 2026 to date.
    for w in range(1, 19):
        week_games = fetch_week(2026, 2, w)
        if not week_games:
            break
        for g in week_games:
            update(ratings, g)
            n += 1
    return ratings, n


def win_prob(ratings, home, away, neutral=False):
    ra = ratings.get(home, 1500.0) + (0.0 if neutral else HFA)
    return expected(ra, ratings.get(away, 1500.0))


def main():
    quiet = "--quiet" in sys.argv
    ratings, n = build()
    from datetime import datetime
    os.makedirs(os.path.dirname(ELO_PATH), exist_ok=True)
    json.dump({"updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
               "games": n,
               "ratings": {t: round(r, 1) for t, r in
                           sorted(ratings.items(), key=lambda x: -x[1])}},
              open(ELO_PATH, "w"), indent=1)
    print(f"elo: {n} games -> {ELO_PATH}")
    if quiet:
        return
    top = sorted(ratings.items(), key=lambda x: -x[1])
    print("\nTOP 10               BOTTOM 5")
    for i in range(10):
        lo = top[-(i + 1)] if i < 5 else ("", "")
        lo_s = f"{lo[0]:<4} {lo[1]:7.1f}" if lo[0] else ""
        print(f"  {top[i][0]:<4} {top[i][1]:7.1f}      {lo_s}")
    # Edges vs the current FanDuel board.
    try:
        events, favs = np.fetch_fd_board()
    except Exception as e:
        print(f"\n(no board comparison: {e})")
        return
    print(f"\nMODEL vs MARKET (upcoming, de-vigged FD favorite):")
    for f in favs:
        away, home = f["matchup"].split(" @ ")
        ep_home = win_prob(ratings, home, away)
        ep_fav = ep_home if f["team"] == home else 1 - ep_home
        edge = ep_fav - f["p"]
        flag = "  <-- edge" if abs(edge) >= 0.04 else ""
        print(f"  {f['matchup']:<12} {f['team']:<4} market "
              f"{f['p']*100:5.1f}%  elo {ep_fav*100:5.1f}%  "
              f"({edge*100:+.1f}){flag}")


if __name__ == "__main__":
    main()
