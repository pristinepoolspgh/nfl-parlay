#!/usr/bin/env python3
"""
nfl_parlay — NFL slate + parlay builder CLI
============================================

Pulls today's NFL games (ESPN public scoreboard API), converts the betting
lines into de-vigged win probabilities, and builds the safest N-leg parlay,
telling you honestly whether your target hit-rate is achievable and what
it pays.

USAGE
  python3 nfl_parlay.py slate                  # today's games + win probs
  python3 nfl_parlay.py parlay                 # best 4-leg parlay
  python3 nfl_parlay.py parlay --legs 3        # best 3-leg parlay
  python3 nfl_parlay.py parlay --target 0.90   # aim for 90% combined
  python3 nfl_parlay.py parlay --stake 25      # payout math on $25
  python3 nfl_parlay.py slate --demo           # offline sample data
  python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)

No API key needed. Live mode requires internet; --demo runs anywhere.
Probabilities are model/market estimates, not guarantees.
"""

import argparse
import json
import sys
import urllib.request
from itertools import combinations

ESPN_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
            "scoreboard")

# ---------------------------------------------------------------- helpers --

def american_to_prob(odds):
    """Implied probability of an American moneyline (includes vig)."""
    if odds is None:
        return None
    odds = float(odds)
    if odds < 0:
        return -odds / (-odds + 100.0)
    return 100.0 / (odds + 100.0)


def prob_to_american(p):
    """Fair American odds for a probability."""
    if p <= 0 or p >= 1:
        return "n/a"
    if p >= 0.5:
        return f"-{round(p / (1 - p) * 100):d}"
    return f"+{round((1 - p) / p * 100):d}"


def devig(p_home, p_away):
    """Strip the bookmaker's vig so the pair sums to 1."""
    total = p_home + p_away
    if total <= 0:
        return p_home, p_away
    return p_home / total, p_away / total


# ------------------------------------------------------------- data layer --

def fetch_live(date=None):
    url = ESPN_URL + (f"?dates={date}" if date else "")
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-parlay-cli"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def parse_espn(payload):
    """ESPN scoreboard JSON -> list of games with de-vigged win probs."""
    games = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("state") != "pre":
            continue  # only games that haven't kicked off
        teams = {c["homeAway"]: c for c in comp.get("competitors", [])}
        home = teams.get("home", {}).get("team", {}).get("abbreviation", "?")
        away = teams.get("away", {}).get("team", {}).get("abbreviation", "?")

        p_home = p_away = None
        for o in comp.get("odds", []):
            hml = (o.get("homeTeamOdds") or {}).get("moneyLine")
            aml = (o.get("awayTeamOdds") or {}).get("moneyLine")
            if hml is not None and aml is not None:
                p_home, p_away = devig(american_to_prob(hml),
                                       american_to_prob(aml))
                break
        if p_home is None:
            continue  # no line posted yet
        games.append({"home": home, "away": away,
                      "p_home": p_home, "p_away": p_away,
                      "start": ev.get("date", "")[:16].replace("T", " ")})
    return games


# Offline sample: the real Sunday Sep 20, 2026 pregame slate (model probs).
DEMO_GAMES = [
    {"home": "TEN", "away": "PHI", "p_home": .242, "p_away": .758, "start": "2026-09-20 13:00"},
    {"home": "NE",  "away": "PIT", "p_home": .673, "p_away": .327, "start": "2026-09-20 13:00"},
    {"home": "CHI", "away": "MIN", "p_home": .661, "p_away": .339, "start": "2026-09-20 13:00"},
    {"home": "ATL", "away": "CAR", "p_home": .437, "p_away": .563, "start": "2026-09-20 13:00"},
    {"home": "NYJ", "away": "GB",  "p_home": .390, "p_away": .610, "start": "2026-09-20 13:00"},
    {"home": "BAL", "away": "NO",  "p_home": .778, "p_away": .222, "start": "2026-09-20 13:00"},
    {"home": "HOU", "away": "CIN", "p_home": .580, "p_away": .420, "start": "2026-09-20 13:00"},
    {"home": "TB",  "away": "CLE", "p_home": .783, "p_away": .217, "start": "2026-09-20 13:00"},
    {"home": "DEN", "away": "JAC", "p_home": .577, "p_away": .423, "start": "2026-09-20 16:05"},
    {"home": "LAC", "away": "LV",  "p_home": .735, "p_away": .265, "start": "2026-09-20 16:05"},
]


def load_games(args):
    if args.demo:
        return DEMO_GAMES
    try:
        return parse_espn(fetch_live(args.date))
    except Exception as e:
        sys.exit(f"Couldn't reach ESPN ({e}). "
                 f"Check your connection or run with --demo.")


# ---------------------------------------------------------------- commands --

def cmd_slate(args):
    games = load_games(args)
    if not games:
        print("No upcoming games with posted lines found.")
        return
    print(f"\n{'MATCHUP':<16}{'KICKOFF':<18}{'FAVORITE':<10}"
          f"{'WIN %':>7}{'FAIR ML':>9}")
    print("-" * 60)
    for g in sorted(games, key=lambda x: -max(x["p_home"], x["p_away"])):
        if g["p_home"] >= g["p_away"]:
            fav, p = g["home"], g["p_home"]
        else:
            fav, p = g["away"], g["p_away"]
        print(f"{g['away']} @ {g['home']:<11}{g['start']:<18}{fav:<10}"
              f"{p*100:>6.1f}%{prob_to_american(p):>9}")
    print(f"\n{len(games)} games with lines. "
          f"Probabilities are de-vigged market estimates.\n")


def cmd_parlay(args):
    games = load_games(args)
    if len(games) < args.legs:
        sys.exit(f"Only {len(games)} games available — can't build "
                 f"a {args.legs}-leg parlay.")

    # Candidate legs = the favorite in every game.
    legs = []
    for g in games:
        if g["p_home"] >= g["p_away"]:
            legs.append((g["home"], f"{g['away']} @ {g['home']}", g["p_home"]))
        else:
            legs.append((g["away"], f"{g['away']} @ {g['home']}", g["p_away"]))

    # Safest N-leg combo = the N highest-probability favorites.
    best = max(combinations(legs, args.legs),
               key=lambda c: prod(p for *_ , p in c))
    combined = prod(p for *_, p in best)
    fair_dec = 1.0 / combined
    payout = args.stake * fair_dec

    print(f"\nSAFEST {args.legs}-LEG MONEYLINE PARLAY "
          f"({len(games)} games on the board)")
    print("-" * 60)
    for i, (team, matchup, p) in enumerate(
            sorted(best, key=lambda x: -x[2]), 1):
        print(f"  LEG {i}: {team:<5} ML  ({matchup:<12}) "
              f"{p*100:5.1f}%  fair {prob_to_american(p)}")
    print("-" * 60)
    print(f"  COMBINED HIT PROBABILITY : {combined*100:.1f}%")
    print(f"  FAIR PARLAY PRICE        : {prob_to_american(combined)}"
          f"  (books pay less after vig)")
    print(f"  ${args.stake:.0f} RETURNS (fair)      : "
          f"${payout:.2f}  (${payout - args.stake:.2f} profit)")

    if args.target:
        per_leg = args.target ** (1.0 / args.legs)
        print(f"\n  TARGET {args.target*100:.0f}% CHECK")
        if combined >= args.target:
            print(f"  ✓ This ticket clears your target.")
        else:
            print(f"  ✗ Not reachable on moneylines today. "
                  f"{args.target*100:.0f}% over {args.legs} legs needs "
                  f"~{per_leg*100:.1f}% per leg "
                  f"(≈ {prob_to_american(per_leg)} each).")
            print(f"    That lives in alternate spreads (e.g. these same "
                  f"teams at +13.5/+14.5), and a true "
                  f"{args.target*100:.0f}% parlay pays about "
                  f"{prob_to_american(args.target)} — "
                  f"${args.stake:.0f} wins roughly "
                  f"${args.stake*(1/args.target-1):.2f}.")
    print("\n  Estimates, not guarantees. Nothing here is betting advice.\n")


def prod(it):
    out = 1.0
    for x in it:
        out *= x
    return out


# ------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(
        prog="nfl_parlay",
        description="NFL slate + safest-parlay builder (ESPN public data).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--demo", action="store_true",
                        help="use bundled offline sample data")
    common.add_argument("--date", metavar="YYYYMMDD",
                        help="pull a specific date instead of today")

    sub.add_parser("slate", parents=[common],
                   help="list upcoming games with win probabilities")

    pp = sub.add_parser("parlay", parents=[common],
                        help="build the safest N-leg parlay")
    pp.add_argument("--legs", type=int, default=4,
                    help="number of legs (default 4)")
    pp.add_argument("--target", type=float, default=0.90,
                    help="target combined probability, e.g. 0.90 "
                         "(default 0.90; 0 to skip the check)")
    pp.add_argument("--stake", type=float, default=10.0,
                    help="stake for payout math (default $10)")

    args = ap.parse_args()
    if args.cmd == "slate":
        cmd_slate(args)
    else:
        if args.target == 0:
            args.target = None
        cmd_parlay(args)


if __name__ == "__main__":
    main()
