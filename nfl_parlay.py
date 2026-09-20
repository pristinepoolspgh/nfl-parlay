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
  python3 nfl_parlay.py parlay --props 2       # swap 2 legs for player props
  python3 nfl_parlay.py props DEN              # player prop lines for a game
  python3 nfl_parlay.py props DEN --type rec   # just the receiving props
  python3 nfl_parlay.py slate --demo           # offline sample data
  python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)

No API key needed. Live mode requires internet; --demo runs anywhere.
Probabilities are model/market estimates, not guarantees.

A note on props: ESPN publishes prop LINES but not prices. A prop at the
market line is roughly a coin flip whichever side you take (books charge
about -110 a side), so prop legs are priced at 50% here and the side is
yours to pick. This tool won't invent an edge it doesn't have.
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from itertools import combinations

try:
    from zoneinfo import ZoneInfo
    _EASTERN = ZoneInfo("America/New_York")
except Exception:  # no tzdata available — fall back to raw UTC
    _EASTERN = None

ESPN_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
            "scoreboard")
PROPS_URL = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
             "nfl/events/{eid}/competitions/{eid}/odds/100/propBets"
             "?limit=300&page={page}")

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

def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-parlay-cli"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def fetch_live(date=None):
    return _get_json(ESPN_URL + (f"?dates={date}" if date else ""))


def fetch_props(event_id):
    """All prop-bet items ESPN lists for a game (paged endpoint)."""
    items, page = [], 1
    while True:
        p = _get_json(PROPS_URL.format(eid=event_id, page=page))
        items.extend(p.get("items", []))
        if page >= p.get("pageCount", 1):
            return items
        page += 1


def _athlete_name(ref, cache):
    """Resolve an ESPN athlete $ref to (name, position), one fetch each."""
    if ref not in cache:
        try:
            a = _get_json(ref)
            cache[ref] = (a.get("displayName", "?"),
                          (a.get("position") or {}).get("abbreviation", ""))
        except Exception:
            cache[ref] = ("(unknown player)", "")
    return cache[ref]


def _kickoff_et(iso):
    """ESPN UTC timestamp ('2026-09-20T20:05Z') -> 'YYYY-MM-DD HH:MM' ET."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if _EASTERN is None:
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return dt.astimezone(_EASTERN).strftime("%Y-%m-%d %H:%M")


def _ml_odds(side):
    """Moneyline from ESPN's nested schema: {'close': {'odds': '-148'}, ...}.

    Prefers the closing line, falls back to the opener. Returns a float
    American price, or None if no usable number is posted.
    """
    if not side:
        return None
    for k in ("close", "open"):
        odds = (side.get(k) or {}).get("odds")
        if odds is None:
            continue
        s = str(odds).strip().lstrip("+").upper()
        if s in ("EVEN", "EV"):
            return 100.0
        try:
            return float(s)
        except ValueError:
            continue
    return None


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
            # Older schema: flat numeric moneyLine on the team odds objects.
            hml = (o.get("homeTeamOdds") or {}).get("moneyLine")
            aml = (o.get("awayTeamOdds") or {}).get("moneyLine")
            if hml is None or aml is None:
                # Current schema: odds[].moneyline.home/away.close.odds
                ml = o.get("moneyline") or {}
                hml = _ml_odds(ml.get("home"))
                aml = _ml_odds(ml.get("away"))
            if hml is not None and aml is not None:
                p_home, p_away = devig(american_to_prob(hml),
                                       american_to_prob(aml))
                break
        if p_home is None:
            continue  # no line posted yet
        games.append({"home": home, "away": away,
                      "p_home": p_home, "p_away": p_away,
                      "start": _kickoff_et(ev.get("date", ""))})
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


# Offline sample props: the real JAX @ DEN lines from Sun Sep 20, 2026.
DEMO_PROPS = [
    {"player": "Trevor Lawrence",   "pos": "QB", "type": "Total Passing Yards",   "line": 223.5},
    {"player": "Bo Nix",            "pos": "QB", "type": "Total Passing Yards",   "line": 221.5},
    {"player": "J.K. Dobbins",      "pos": "RB", "type": "Total Rushing Yards",   "line": 58.5},
    {"player": "Bhayshul Tuten",    "pos": "RB", "type": "Total Rushing Yards",   "line": 49.5},
    {"player": "Parker Washington", "pos": "WR", "type": "Total Receiving Yards", "line": 59.5},
    {"player": "Jaylen Waddle",     "pos": "WR", "type": "Total Receiving Yards", "line": 54.5},
    {"player": "Courtland Sutton",  "pos": "WR", "type": "Total Receiving Yards", "line": 40.5},
    {"player": "Brian Thomas Jr.",  "pos": "WR", "type": "Total Receiving Yards", "line": 32.5},
    {"player": "Evan Engram",       "pos": "TE", "type": "Total Receiving Yards", "line": 26.5},
    {"player": "Jaylen Waddle",     "pos": "WR", "type": "Total Receptions",      "line": 4.5},
    {"player": "Parker Washington", "pos": "WR", "type": "Total Receptions",      "line": 4.5},
]
DEMO_PROPS_MATCHUP = "JAX @ DEN"

# Which prop types each --type filter keeps (substring match, lowercased).
PROP_FILTERS = {
    "pass": ["passing"],
    "rush": ["rushing"],
    "rec":  ["receiving", "receptions"],
    "td":   ["touchdown"],
    "all":  [],  # everything with a posted line
}
# With no --type, show only the core full-game props (exact match, so the
# 1st-half/1st-quarter variants don't crowd the board).
DEFAULT_PROP_TYPES = {"total passing yards", "total rushing yards",
                      "total receiving yards", "total receptions"}


def _prop_matches(type_name, type_filter):
    base = type_name.replace(" (incl. overtime)", "").lower()
    if type_filter is None:
        return base in DEFAULT_PROP_TYPES
    keywords = PROP_FILTERS[type_filter]
    return not keywords or any(k in base for k in keywords)


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
    print(f"\n{'MATCHUP':<16}{'KICKOFF (ET)':<18}{'FAVORITE':<10}"
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


def _find_pregame_event(payload, team):
    """(event_id, 'AWY @ HOM') for the team's upcoming game, or None."""
    team = team.upper()
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if comp.get("status", {}).get("type", {}).get("state") != "pre":
            continue
        abbrs = [c.get("team", {}).get("abbreviation", "")
                 for c in comp.get("competitors", [])]
        if team in abbrs:
            return ev.get("id"), ev.get("shortName", " @ ".join(abbrs))
    return None


def cmd_props(args):
    if args.demo:
        matchup, total = DEMO_PROPS_MATCHUP, len(DEMO_PROPS)
        props = [p for p in DEMO_PROPS
                 if _prop_matches(p["type"], args.type)]
    else:
        try:
            payload = fetch_live(args.date)
        except Exception as e:
            sys.exit(f"Couldn't reach ESPN ({e}). "
                     f"Check your connection or run with --demo.")
        found = _find_pregame_event(payload, args.team)
        if not found:
            sys.exit(f"No upcoming game found for '{args.team}'. "
                     f"Run the slate command to see what's on the board.")
        eid, matchup = found
        try:
            raw = fetch_props(eid)
        except Exception as e:
            sys.exit(f"Couldn't fetch props ({e}).")
        # Keep props with a posted line; ESPN lists each one twice, so
        # dedupe on (player, prop type, line).
        lined, seen = [], set()
        for r in raw:
            line = (r.get("current") or {}).get("target", {}).get("value")
            if line is None:
                continue
            key = (r.get("athlete", {}).get("$ref"),
                   r["type"]["name"], line)
            if key in seen:
                continue
            seen.add(key)
            lined.append(r)
        total = len(lined)
        lined = [r for r in lined
                 if _prop_matches(r["type"]["name"], args.type)]
        # Core full-game props first, then the rest alphabetically.
        lined.sort(key=lambda r: (
            r["type"]["name"].replace(" (incl. overtime)", "").lower()
            not in DEFAULT_PROP_TYPES,
            r["type"]["name"],
            -r["current"]["target"]["value"]))
        lined = lined[:args.limit]
        cache = {}
        props = []
        for r in lined:
            name, pos = _athlete_name(r["athlete"]["$ref"], cache)
            props.append({"player": name, "pos": pos,
                          "type": r["type"]["name"],
                          "line": r["current"]["target"]["value"]})

    if not props:
        print("No props matched that filter.")
        return
    print(f"\nPLAYER PROP LINES — {matchup}  "
          f"(showing {len(props)} of {total} posted)")
    print("-" * 66)
    print(f"{'PLAYER':<24}{'POS':<5}{'PROP':<30}{'LINE':>7}")
    print("-" * 66)
    for p in props:
        label = p["type"].replace(" (incl. overtime)", "")
        print(f"{p['player']:<24}{p['pos']:<5}{label:<30}{p['line']:>7g}")
    print("\nESPN publishes prop lines, not prices. At the market line either"
          "\nside is ~50/50 before the book's ~-110 juice. Pick your side —"
          "\nthe parlay math (parlay --props N) is the same either way.\n")


def cmd_parlay(args):
    games = load_games(args)
    n_props = args.props
    if not 0 <= n_props <= args.legs:
        sys.exit(f"--props must be between 0 and --legs ({args.legs}).")
    n_ml = args.legs - n_props
    if len(games) < n_ml:
        sys.exit(f"Only {len(games)} games available — can't build "
                 f"a parlay with {n_ml} moneyline legs.")

    # Candidate legs = the favorite in every game.
    legs = []
    for g in games:
        if g["p_home"] >= g["p_away"]:
            legs.append((g["home"], f"{g['away']} @ {g['home']}", g["p_home"]))
        else:
            legs.append((g["away"], f"{g['away']} @ {g['home']}", g["p_away"]))

    # Safest combo of moneyline legs = the highest-probability favorites.
    best = ()
    if n_ml:
        best = max(combinations(legs, n_ml),
                   key=lambda c: prod(p for *_ , p in c))
    combined = prod(p for *_, p in best) * 0.5 ** n_props
    fair_dec = 1.0 / combined
    payout = args.stake * fair_dec

    label = "MONEYLINE" if not n_props else "MONEYLINE + PROPS"
    print(f"\nSAFEST {args.legs}-LEG {label} PARLAY "
          f"({len(games)} games on the board)")
    print("-" * 60)
    n = 0
    for n, (team, matchup, p) in enumerate(
            sorted(best, key=lambda x: -x[2]), 1):
        print(f"  LEG {n}: {team:<5} ML  ({matchup:<12}) "
              f"{p*100:5.1f}%  fair {prob_to_american(p)}")
    for i in range(n + 1, n + 1 + n_props):
        print(f"  LEG {i}: PROP  your pick, either side   "
              f" 50.0%  fair +100")
    print("-" * 60)
    print(f"  COMBINED HIT PROBABILITY : {combined*100:.1f}%")
    print(f"  FAIR PARLAY PRICE        : {prob_to_american(combined)}"
          f"  (books pay less after vig)")
    print(f"  ${args.stake:.0f} RETURNS (fair)      : "
          f"${payout:.2f}  (${payout - args.stake:.2f} profit)")

    if n_props:
        print(f"\n  Prop legs: ESPN posts lines without prices, and a prop at"
              f"\n  the market line is ≈50/50 whichever side you take — so"
              f"\n  each prop leg halves the ticket's chances and roughly"
              f"\n  doubles its fair payout. Browse lines with: props <TEAM>")

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
    pp.add_argument("--props", type=int, default=0,
                    help="of those legs, how many are player props "
                         "(pick-your-side, ~50%% each; default 0)")
    pp.add_argument("--target", type=float, default=0.90,
                    help="target combined probability, e.g. 0.90 "
                         "(default 0.90; 0 to skip the check)")
    pp.add_argument("--stake", type=float, default=10.0,
                    help="stake for payout math (default $10)")

    pr = sub.add_parser("props", parents=[common],
                        help="list player prop lines for a team's next game")
    pr.add_argument("team", nargs="?", default="",
                    help="team abbreviation, e.g. DEN (any team in the game)")
    pr.add_argument("--type", choices=sorted(PROP_FILTERS),
                    help="filter: pass, rush, rec, td, or all "
                         "(default: the core yardage/receptions props)")
    pr.add_argument("--limit", type=int, default=20,
                    help="max props to show (default 20)")

    args = ap.parse_args()
    if args.cmd == "slate":
        cmd_slate(args)
    elif args.cmd == "props":
        if not args.team and not args.demo:
            ap.error("props needs a team abbreviation (e.g. props DEN), "
                     "or --demo")
        cmd_props(args)
    else:
        if args.target == 0:
            args.target = None
        cmd_parlay(args)


if __name__ == "__main__":
    main()
