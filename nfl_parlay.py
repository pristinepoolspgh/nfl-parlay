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
  python3 nfl_parlay.py props DEN              # player props with prices
  python3 nfl_parlay.py props DEN --alts       # include alternate lines
  python3 nfl_parlay.py props DEN --type rec   # just the receiving props
  python3 nfl_parlay.py slate --demo           # offline sample data
  python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)

No API key needed. Live mode requires internet; --demo runs anywhere.
Probabilities are model/market estimates, not guarantees.

DATA SOURCES
  Game moneylines come from ESPN's public scoreboard API. Player prop
  PRICES come from Bovada's public JSON (both sides of every line,
  alternates included), de-vigged the same way as the moneylines. If
  Bovada is unreachable, props fall back to ESPN, which publishes only
  the lines — a prop at the market line is ~50/50 either side, and the
  tool says so rather than inventing an edge.

BET LINKS
  By default the parlay builds from FanDuel's own board (moneylines
  and player props, de-vigged from FanDuel's prices) and prints ONE
  link that opens the FanDuel app with every leg already on the slip.
  With --book espn, moneyline legs get per-leg DraftKings slip links
  (the slip keeps earlier picks as you tap each) and prop legs open
  the game's Bovada board.
"""

import argparse
import json
import math
import re
import sys
import urllib.parse
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
BOVADA_COUPON = ("https://www.bovada.lv/services/sports/event/coupon/events/"
                 "A/description/football/nfl"
                 "?marketFilterId=def&preMatchOnly=true&lang=en")
BOVADA_EVENT = ("https://www.bovada.lv/services/sports/event/v2/events/"
                "A/description{link}?lang=en")

# FanDuel's public web API key, embedded in their own site's page source.
FD_AK = "FhMFpcPWXMeyZxOx"
FD_PAGE = ("https://sbapi.pa.sportsbook.fanduel.com/api/content-managed-page"
           f"?page=CUSTOM&customPageId=nfl&pbHorizontal=false&_ak={FD_AK}"
           "&timezone=America%2FNew_York")
FD_EVENT = ("https://sbapi.pa.sportsbook.fanduel.com/api/event-page"
            f"?_ak={FD_AK}" "&eventId={eid}&tab={tab}")
FD_PROP_TABS = ("passing-props", "rushing-props", "receiving-props")
FD_BETSLIP = "https://sportsbook.fanduel.com/addToBetslip"

# ESPN-style abbreviations -> nicknames, for matching Bovada event names.
TEAM_NICKNAMES = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "JAC": "Jaguars",
    "KC": "Chiefs", "LAC": "Chargers", "LAR": "Rams", "LV": "Raiders",
    "MIA": "Dolphins", "MIN": "Vikings", "NE": "Patriots", "NO": "Saints",
    "NYG": "Giants", "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers",
    "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans",
    "WSH": "Commanders", "WAS": "Commanders",
}

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
    # A browser-ish UA: some books' public endpoints reject unknown agents.
    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
          "Mobile/15E148 Safari/604.1")
    req = urllib.request.Request(url, headers={"User-Agent": ua})
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


# ------------------------------------------------- Bovada (priced props) --

def fetch_bovada_events():
    """Bovada's pregame NFL events: [{'description', 'link'}, ...]."""
    events = []
    for grp in _get_json(BOVADA_COUPON):
        events.extend(grp.get("events", []))
    return events


_BOVADA_PLAYER = re.compile(r"^(.+?) - (.+?) \((\w{2,3})\)$")


def parse_bovada_props(payload, url=None):
    """Bovada event JSON -> player O/U props with priced lines.

    Each prop: {player, team, type, matchup, url,
                lines: [{line, over, under}, ...]}  (American prices)
    """
    ev = payload[0]["events"][0]
    matchup = ev.get("description", "")
    props = []
    for g in ev.get("displayGroups", []):
        for m in g.get("markets", []):
            if m.get("key") != "2W-OU" or not (m.get("period") or {}).get("main"):
                continue
            mt = _BOVADA_PLAYER.match(m.get("description", ""))
            if not mt:
                continue  # game/team market, not a player prop
            ptype, player, team = mt.groups()
            pairs = {}
            for o in m.get("outcomes", []):
                if o.get("status") != "O":
                    continue
                pr = o.get("price") or {}
                h, am = pr.get("handicap"), pr.get("american")
                if h is None or am is None:
                    continue
                if str(am).upper() in ("EVEN", "EV"):
                    am = 100.0
                pairs.setdefault(float(h), {})[o.get("type")] = float(am)
            lines = [{"line": h, "over": v["O"], "under": v["U"]}
                     for h, v in sorted(pairs.items())
                     if "O" in v and "U" in v]
            if lines:
                props.append({"player": player, "team": team, "type": ptype,
                              "matchup": matchup, "url": url,
                              "lines": lines})
    return props


def fetch_bovada_props(link):
    return parse_bovada_props(_get_json(BOVADA_EVENT.format(link=link)),
                              url="https://www.bovada.lv/sports" + link)


def _match_bovada_event(events, team):
    """Find the event whose name contains the team (abbrev or name)."""
    needle = TEAM_NICKNAMES.get(team.upper(), team).lower()
    for e in events:
        if needle in e.get("description", "").lower():
            return e
    return None


def prop_probs(ln):
    """De-vigged (p_over, p_under) for one priced line."""
    return devig(american_to_prob(ln["over"]), american_to_prob(ln["under"]))


def main_line(prop):
    """The market's main line: the one closest to a coin flip."""
    return min(prop["lines"],
               key=lambda ln: abs(prop_probs(ln)[0] - 0.5))


def best_prop_side(prop):
    """(side, line, prob) for the safest side across all posted lines."""
    best = None
    for ln in prop["lines"]:
        po, pu = prop_probs(ln)
        for side, p in (("Over", po), ("Under", pu)):
            if best is None or p > best[2]:
                best = (side, ln, p)
    return best


def _fmt_am(x):
    return f"{int(x):+d}"


# ------------------------------------- FanDuel (one-tap bet-slip links) --

def _abbr(full_name):
    """'Kansas City Chiefs' -> 'KC' via the nickname table."""
    for ab, nick in TEAM_NICKNAMES.items():
        if nick in full_name:
            return ab
    return full_name


def _fd_odds(runner):
    o = ((runner.get("winRunnerOdds") or {})
         .get("americanDisplayOdds") or {}).get("americanOdds")
    return None if o is None else float(o)


def fetch_fd_board():
    """FanDuel's NFL page -> pregame moneyline candidates with slip IDs.

    Returns (events, favorites): events as {id: 'AWY @ HOM'}, favorites as
    [{team, matchup, p, odds, market, sel}] best side per game, best first.
    """
    page = _get_json(FD_PAGE)
    att = page.get("attachments", {})
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    events = {}
    for eid, ev in att.get("events", {}).items():
        name = ev.get("name", "")
        if " @ " not in name:
            continue  # futures/specials
        if ev.get("openDate", "")[:19] <= now:
            continue  # kicked off
        away, home = name.split(" @ ", 1)
        events[int(eid)] = f"{_abbr(away)} @ {_abbr(home)}"
    favs = []
    for m in att.get("markets", {}).values():
        if (m.get("marketType") != "MONEY_LINE"
                or m.get("marketStatus") != "OPEN"
                or m.get("eventId") not in events):
            continue
        runners = [r for r in m.get("runners", [])
                   if r.get("runnerStatus") == "ACTIVE"
                   and _fd_odds(r) is not None]
        if len(runners) != 2:
            continue
        pa, pb = devig(american_to_prob(_fd_odds(runners[0])),
                       american_to_prob(_fd_odds(runners[1])))
        r, p = (runners[0], pa) if pa >= pb else (runners[1], pb)
        favs.append({"team": _abbr(r.get("runnerName", "?")),
                     "matchup": events[m["eventId"]],
                     "p": p, "odds": _fd_odds(r),
                     "market": m["marketId"], "sel": r["selectionId"]})
    favs.sort(key=lambda f: -f["p"])
    return events, favs


def fetch_fd_props(event_id, matchup):
    """One event's main player O/U props with slip IDs and de-vigged probs."""
    props = []
    for tab in FD_PROP_TABS:
        try:
            page = _get_json(FD_EVENT.format(eid=event_id, tab=tab))
        except Exception:
            continue
        for m in page.get("attachments", {}).get("markets", {}).values():
            mtype = m.get("marketType", "")
            if (not mtype.startswith("PLAYER_")
                    or "_ALT_" in mtype
                    or m.get("marketStatus") != "OPEN"
                    or " - " not in m.get("marketName", "")):
                continue
            player, label = m["marketName"].split(" - ", 1)
            over = under = None
            for r in m.get("runners", []):
                if r.get("runnerStatus") != "ACTIVE" or _fd_odds(r) is None:
                    continue
                if r.get("runnerName", "").endswith("Over"):
                    over = r
                elif r.get("runnerName", "").endswith("Under"):
                    under = r
            if not over or not under:
                continue
            po, pu = devig(american_to_prob(_fd_odds(over)),
                           american_to_prob(_fd_odds(under)))
            side, r, p = (("Over", over, po) if po >= pu
                          else ("Under", under, pu))
            props.append({"player": player, "type": label,
                          "matchup": matchup, "side": side,
                          "line": r.get("handicap"), "p": p,
                          "odds": _fd_odds(r),
                          "market": m["marketId"], "sel": r["selectionId"]})
    return props


def fd_ticket_url(legs):
    """One FanDuel link that loads every leg onto the bet slip."""
    parts = []
    for i, l in enumerate(legs):
        parts.append(f"marketId[{i}]={l['market']}"
                     f"&selectionId[{i}]={l['sel']}")
    return FD_BETSLIP + "?" + "&".join(parts)


def fd_decimal(american):
    """Decimal odds for an American price."""
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


def fd_posted_payout(stake, legs):
    """What FanDuel pays at posted prices (standard cross-game parlay)."""
    return stake * prod(fd_decimal(l["odds"]) for l in legs)


_ALT_SPREAD_RE = re.compile(r"^(.+?) \(([+-]\d+(?:\.\d)?)\)$")
_ALT_TOTAL_RE = re.compile(r"^(Over|Under) \((\d+(?:\.\d)?)\)$")


def fetch_fd_alts(event_id, matchup):
    """Alternate spread/total rungs for one game, de-vigged in mirror
    pairs (team A +7.5 against team B -7.5; Over against Under).

    Returns candidate legs [{desc, p, odds, market, sel, matchup}].
    """
    try:
        page = _get_json(FD_EVENT.format(eid=event_id, tab="popular"))
    except Exception:
        return []
    legs = []
    for m in page.get("attachments", {}).get("markets", {}).values():
        mt = m.get("marketType")
        if (m.get("marketStatus") != "OPEN"
                or mt not in ("ALTERNATE_HANDICAP", "ALTERNATE_TOTAL")):
            continue
        entries = {}
        for r in m.get("runners", []):
            if r.get("runnerStatus") != "ACTIVE":
                continue
            odds = _fd_odds(r)
            if odds is None:
                continue
            name = r.get("runnerName", "")
            if mt == "ALTERNATE_HANDICAP":
                mm = _ALT_SPREAD_RE.match(name)
                if not mm:
                    continue
                who, line = _abbr(mm.group(1)), float(mm.group(2))
                desc = f"{who} {line:+g}"
            else:
                mm = _ALT_TOTAL_RE.match(name)
                if not mm:
                    continue
                who, line = mm.group(1), float(mm.group(2))
                line = line if who == "Over" else -line
                desc = f"{who} {abs(line):g} pts"
            entries[(who, line)] = (desc, odds, m["marketId"],
                                    r["selectionId"])
        done = set()
        for (who, line), a in entries.items():
            if line <= 0 or (who, line) in done:
                continue
            comp = next((k for k in entries
                         if k[0] != who and k[1] == -line), None)
            if comp is None:
                continue
            done.add((who, line))
            done.add(comp)
            b = entries[comp]
            pa, pb = devig(american_to_prob(a[1]), american_to_prob(b[1]))
            for (desc, odds, mid, sel), p in ((a, pa), (b, pb)):
                legs.append({"desc": desc, "p": p, "odds": odds,
                             "market": mid, "sel": sel, "matchup": matchup})
    return legs


def build_target_ticket(events, target, n_legs, favorites=None):
    """A ticket whose combined probability clears the target while
    paying as much as the board allows: start each game at its safest
    alternate line, then walk legs down toward better prices for as
    long as the product stays over the target. Moneyline favorites
    compete in each game's ladder alongside the alternates.

    Returns (picks, achieved_or_best, games_with_alts); picks is None
    when the target is out of reach, with achieved_or_best then the
    best combined probability the board offers.
    """
    ml = {f["matchup"]: f for f in favorites or []}
    per_game = []
    for eid, matchup in events.items():
        rungs = fetch_fd_alts(eid, matchup)
        if matchup in ml:
            f = ml[matchup]
            rungs.append({"desc": f"{f['team']} ML", "p": f["p"],
                          "odds": f["odds"], "market": f["market"],
                          "sel": f["sel"], "matchup": matchup})
        rungs.sort(key=lambda a: a["p"])
        if rungs:
            per_game.append(rungs)
    if len(per_game) < n_legs:
        return None, 0.0, len(per_game)
    per_game.sort(key=lambda r: -r[-1]["p"])
    chosen = per_game[:n_legs]
    idx = [len(r) - 1 for r in chosen]
    current = prod(r[i]["p"] for r, i in zip(chosen, idx))
    if current < target:
        return None, current, len(per_game)
    # Repeatedly take the single move that buys the most payout per
    # unit of probability spent, until no move keeps the target.
    while True:
        best_move = None
        for j, rungs in enumerate(chosen):
            i = idx[j]
            for i2 in range(i):
                r = rungs[i2]["p"] / rungs[i]["p"]
                if current * r < target:
                    continue
                q = (fd_decimal(rungs[i2]["odds"])
                     / fd_decimal(rungs[i]["odds"]))
                if q <= 1:
                    continue
                value = math.log(q) / max(-math.log(r), 1e-9)
                if best_move is None or value > best_move[0]:
                    best_move = (value, j, i2)
        if best_move is None:
            break
        _, j, i2 = best_move
        current *= chosen[j][i2]["p"] / chosen[j][idx[j]]["p"]
        idx[j] = i2
    picks = [r[i] for r, i in zip(chosen, idx)]
    return picks, current, len(per_game)


def _kickoff_et(iso):
    """ESPN UTC timestamp ('2026-09-20T20:05Z') -> 'YYYY-MM-DD HH:MM' ET."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if _EASTERN is None:
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return dt.astimezone(_EASTERN).strftime("%Y-%m-%d %H:%M")


def _dk_link(side):
    """DraftKings bet-slip deep link from an ESPN moneyline side, if any.

    ESPN wraps it in a tracking gateway URL; the clean event link rides
    in the 'preurl' parameter.
    """
    href = (((side or {}).get("close") or {}).get("link") or {}).get("href", "")
    if "preurl=" not in href:
        return None
    raw = href.split("preurl=", 1)[1].split("&", 1)[0]
    url = urllib.parse.unquote(raw)
    return url if url.startswith("https://sportsbook.draftkings.com/") else None


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
        dk_home = dk_away = None
        for o in comp.get("odds", []):
            ml = o.get("moneyline") or {}
            # Older schema: flat numeric moneyLine on the team odds objects.
            hml = (o.get("homeTeamOdds") or {}).get("moneyLine")
            aml = (o.get("awayTeamOdds") or {}).get("moneyLine")
            if hml is None or aml is None:
                # Current schema: odds[].moneyline.home/away.close.odds
                hml = _ml_odds(ml.get("home"))
                aml = _ml_odds(ml.get("away"))
            if hml is not None and aml is not None:
                p_home, p_away = devig(american_to_prob(hml),
                                       american_to_prob(aml))
                dk_home = _dk_link(ml.get("home"))
                dk_away = _dk_link(ml.get("away"))
                break
        if p_home is None:
            continue  # no line posted yet
        games.append({"home": home, "away": away,
                      "p_home": p_home, "p_away": p_away,
                      "dk_home": dk_home, "dk_away": dk_away,
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


# Offline sample props: real JAX @ DEN Bovada prices from Sun Sep 20, 2026.
DEMO_PROPS_MATCHUP = "Jacksonville Jaguars @ Denver Broncos"
DEMO_PROPS = [
    {"player": "Bo Nix", "team": "DEN", "type": "Total Passing Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 191.5, "over": -250, "under": 185},
        {"line": 201.5, "over": -190, "under": 145},
        {"line": 211.5, "over": -145, "under": 110},
        {"line": 221.5, "over": -115, "under": -115},
        {"line": 231.5, "over": 110, "under": -145},
        {"line": 241.5, "over": 140, "under": -185},
        {"line": 251.5, "over": 175, "under": -240}]},
    {"player": "Trevor Lawrence", "team": "JAX", "type": "Total Passing Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 193.5, "over": -250, "under": 185},
        {"line": 213.5, "over": -145, "under": 110},
        {"line": 223.5, "over": -115, "under": -115},
        {"line": 243.5, "over": 140, "under": -185}]},
    {"player": "J.K. Dobbins", "team": "DEN", "type": "Total Rushing Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 48.5, "over": -200, "under": 150},
        {"line": 58.5, "over": -110, "under": -120},
        {"line": 68.5, "over": 150, "under": -200}]},
    {"player": "Bhayshul Tuten", "team": "JAX", "type": "Total Rushing Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 39.5, "over": -220, "under": 165},
        {"line": 49.5, "over": -115, "under": -115},
        {"line": 59.5, "over": 150, "under": -200}]},
    {"player": "Chris Rodriguez", "team": "JAX", "type": "Total Rushing Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 15.5, "over": -310, "under": 225},
        {"line": 25.5, "over": -110, "under": -120},
        {"line": 35.5, "over": 190, "under": -260}]},
    {"player": "Parker Washington", "team": "JAX",
     "type": "Total Receiving Yards", "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 49.5, "over": -185, "under": 140},
        {"line": 59.5, "over": -115, "under": -115},
        {"line": 69.5, "over": 135, "under": -180}]},
    {"player": "Jaylen Waddle", "team": "DEN",
     "type": "Total Receiving Yards", "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 44.5, "over": -185, "under": 140},
        {"line": 54.5, "over": -110, "under": -120},
        {"line": 64.5, "over": 140, "under": -185}]},
    {"player": "Courtland Sutton", "team": "DEN",
     "type": "Total Receiving Yards", "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 30.5, "over": -215, "under": 160},
        {"line": 40.5, "over": -115, "under": -115},
        {"line": 50.5, "over": 145, "under": -190}]},
    {"player": "Evan Engram", "team": "DEN", "type": "Total Receiving Yards",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 26.5, "over": -110, "under": -120}]},
    {"player": "Jaylen Waddle", "team": "DEN", "type": "Total Receptions",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 4.5, "over": 105, "under": -135}]},
    {"player": "Brian Thomas", "team": "JAX", "type": "Total Receptions",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 2.5, "over": -125, "under": -105}]},
    {"player": "Courtland Sutton", "team": "DEN", "type": "Total Receptions",
     "matchup": DEMO_PROPS_MATCHUP, "lines": [
        {"line": 3.5, "over": -110, "under": -120}]},
]

# Which prop types each --type filter keeps (substring match, lowercased).
PROP_FILTERS = {
    "pass": ["passing"],
    "rush": ["rushing"],
    "rec":  ["receiving", "reception"],
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


def _sort_props(props):
    """Core full-game props first, then the rest alphabetically."""
    props.sort(key=lambda p: (p["type"].lower() not in DEFAULT_PROP_TYPES,
                              p["type"],
                              -main_line(p)["line"]))


def _print_priced_props(matchup, props, total, show_alts):
    if not props:
        print("No props matched that filter.")
        return
    print(f"\nPLAYER PROPS — {matchup}  (showing {len(props)} of {total})")
    print("-" * 78)
    print(f"{'PLAYER':<25}{'PROP':<18}{'LINE':>7}"
          f"{'OVER':>14}{'UNDER':>14}")
    print("-" * 78)
    for p in props:
        label = p["type"].replace("Total ", "")
        lines = (sorted(p["lines"], key=lambda l: l["line"])
                 if show_alts else [main_line(p)])
        first = True
        for ln in lines:
            po, pu = prop_probs(ln)
            who = f"{p['player']} ({p['team']})" if first else ""
            print(f"{who:<25}{label if first else '':<18}{ln['line']:>7g}"
                  f"{po*100:>6.1f}% {_fmt_am(ln['over']):>6}"
                  f"{pu*100:>6.1f}% {_fmt_am(ln['under']):>6}")
            first = False
    print("\nPrices from Bovada, probabilities de-vigged (each line's two"
          "\nsides sum to 100%). The posted price is what the book pays;"
          "\nthe fair price for that probability is always better.")
    url = next((p.get("url") for p in props if p.get("url")), None)
    if url:
        print(f"Bet this board: {url}")
    print()


def _cmd_props_espn(args):
    """Fallback: ESPN publishes prop lines but no prices."""
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
        key = (r.get("athlete", {}).get("$ref"), r["type"]["name"], line)
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
          f"(showing {len(props)} of {total} posted; ESPN, no prices)")
    print("-" * 66)
    print(f"{'PLAYER':<24}{'POS':<5}{'PROP':<30}{'LINE':>7}")
    print("-" * 66)
    for p in props:
        label = p["type"].replace(" (incl. overtime)", "")
        print(f"{p['player']:<24}{p['pos']:<5}{label:<30}{p['line']:>7g}")
    print("\nESPN publishes prop lines, not prices. At the market line either"
          "\nside is ~50/50 before the book's ~-110 juice.\n")


def cmd_props(args):
    if args.demo:
        props = [p for p in DEMO_PROPS if _prop_matches(p["type"], args.type)]
        _sort_props(props)
        _print_priced_props(DEMO_PROPS_MATCHUP, props[:args.limit],
                            len(DEMO_PROPS), args.alts)
        return
    if args.source == "espn":
        _cmd_props_espn(args)
        return
    try:
        events = fetch_bovada_events()
        ev = _match_bovada_event(events, args.team)
        if ev is None:
            sys.exit(f"No upcoming game found for '{args.team}' on Bovada. "
                     f"Run the slate command to see what's on the board.")
        props = fetch_bovada_props(ev["link"])
    except SystemExit:
        raise
    except Exception as e:
        if args.source == "bovada":
            sys.exit(f"Couldn't fetch props from Bovada ({e}).")
        print(f"Bovada unreachable ({e}) — falling back to ESPN lines.",
              file=sys.stderr)
        _cmd_props_espn(args)
        return
    total = len(props)
    props = [p for p in props if _prop_matches(p["type"], args.type)]
    _sort_props(props)
    if not props:
        print("No props matched that filter.")
        return
    _print_priced_props(ev["description"], props[:args.limit], total,
                        args.alts)


SHORT_PROP = {"Total Passing Yards": "Pass Yds",
              "Total Rushing Yards": "Rush Yds",
              "Total Receiving Yards": "Rec Yds",
              "Total Receptions": "Recs"}


def prop_leg_candidates(props):
    """Safest priced side per player, core prop types only, best first."""
    by_player = {}
    for pr in props:
        if pr["type"].lower() not in DEFAULT_PROP_TYPES:
            continue
        side, ln, p = best_prop_side(pr)
        cur = by_player.get(pr["player"])
        if cur is None or p > cur["p"]:
            by_player[pr["player"]] = {
                "player": pr["player"], "team": pr["team"],
                "type": pr["type"], "side": side,
                "line": ln["line"], "p": p, "url": pr.get("url")}
    return sorted(by_player.values(), key=lambda c: -c["p"])


def _print_target_check(args, combined, n_props):
    if not args.target:
        return
    per_leg = args.target ** (1.0 / args.legs)
    print(f"\n  TARGET {args.target*100:.0f}% CHECK")
    if combined >= args.target:
        print(f"  ✓ This ticket clears your target.")
    else:
        board = "on this board" if n_props else "on moneylines today"
        print(f"  ✗ Not reachable {board}. "
              f"{args.target*100:.0f}% over {args.legs} legs needs "
              f"~{per_leg*100:.1f}% per leg "
              f"(≈ {prob_to_american(per_leg)} each).")


def build_payout_ticket(events, target_dec, n_legs, favorites=None):
    """The most likely ticket that pays at least the target: start each
    of the n safest games at its highest-probability rung, then trade
    probability for payout as cheaply as possible until the posted
    parlay price reaches the target.

    Returns (picks, combined, reached_dec); picks is None when even
    the longest rungs can't reach the target, with reached_dec then
    the best posted price available at n legs.
    """
    ml = {f["matchup"]: f for f in favorites or []}
    per_game = []
    for eid, matchup in events.items():
        rungs = fetch_fd_alts(eid, matchup)
        if matchup in ml:
            f = ml[matchup]
            rungs.append({"desc": f"{f['team']} ML", "p": f["p"],
                          "odds": f["odds"], "market": f["market"],
                          "sel": f["sel"], "matchup": matchup})
        rungs.sort(key=lambda a: a["p"])
        if rungs:
            per_game.append(rungs)
    if len(per_game) < n_legs:
        return None, 0.0, 0.0
    per_game.sort(key=lambda r: -r[-1]["p"])
    chosen = per_game[:n_legs]
    idx = [len(r) - 1 for r in chosen]
    cur_p = prod(r[i]["p"] for r, i in zip(chosen, idx))
    cur_dec = prod(fd_decimal(r[i]["odds"]) for r, i in zip(chosen, idx))
    while cur_dec < target_dec:
        # A move that clears the target ends the walk: take the one
        # keeping the most probability (the smallest sufficient jump).
        finisher, best = None, None
        for j, rungs in enumerate(chosen):
            i = idx[j]
            for i2 in range(i):
                q = fd_decimal(rungs[i2]["odds"]) / fd_decimal(rungs[i]["odds"])
                if q <= 1:
                    continue
                r = rungs[i2]["p"] / rungs[i]["p"]
                if cur_dec * q >= target_dec:
                    if finisher is None or r > finisher[0]:
                        finisher = (r, j, i2)
                else:
                    value = math.log(q) / max(-math.log(r), 1e-9)
                    if best is None or value > best[0]:
                        best = (value, j, i2)
        move = finisher or best
        if move is None:
            return None, cur_p, cur_dec
        _, j, i2 = move
        cur_p *= chosen[j][i2]["p"] / chosen[j][idx[j]]["p"]
        cur_dec *= (fd_decimal(chosen[j][i2]["odds"])
                    / fd_decimal(chosen[j][idx[j]]["odds"]))
        idx[j] = i2
    picks = [r[i] for r, i in zip(chosen, idx)]
    return picks, cur_p, cur_dec


def _dec_to_american(dec):
    if dec >= 2:
        return f"+{round((dec - 1) * 100)}"
    return f"-{round(100 / (dec - 1))}"


def cmd_parlay_fd(args):
    """Build the ticket from FanDuel's own board and emit one slip link."""
    try:
        events, favs = fetch_fd_board()
    except Exception as e:
        print(f"FanDuel unreachable ({e}) — falling back to ESPN/Bovada.",
              file=sys.stderr)
        return cmd_parlay(args, book="espn")
    if getattr(args, "pay", None):
        target_dec = fd_decimal(args.pay)
        picks, cur_p, cur_dec = build_payout_ticket(events, target_dec,
                                                    args.legs, favs)
        if picks is None:
            top = (_dec_to_american(cur_dec) if cur_dec > 1
                   else "nothing")
            sys.exit(f"{args.legs} legs top out at {top} on today's "
                     f"board — add --legs for longer odds.")
        print(f"\nMOST LIKELY {args.legs}-LEG TICKET PAYING "
              f"{_fmt_am(args.pay)} OR BETTER")
        print("-" * 68)
        for i, p in enumerate(picks, 1):
            print(f"  LEG {i}: {p['desc']:<16} ({p['matchup']:<12}) "
                  f"{p['p']*100:5.1f}%  FD {_fmt_am(p['odds'])}")
        print("-" * 68)
        print(f"  HIT PROBABILITY : {cur_p*100:.1f}%  (fair price "
              f"{prob_to_american(cur_p)})")
        print(f"  FD PAYS         : {_dec_to_american(cur_dec)} — "
              f"${args.stake:.0f} returns ${args.stake*cur_dec:.2f}")
        print(f"\n  ONE-TAP TICKET:")
        print(f"  {fd_ticket_url(picks)}")
        print(f"\n  The price you asked for buys exactly this much "
              f"chance — no more.\n  Estimates, not guarantees. "
              f"Nothing here is betting advice.\n")
        return

    n_props = args.props
    if not 0 <= n_props <= args.legs:
        sys.exit(f"--props must be between 0 and --legs ({args.legs}).")
    n_ml = args.legs - n_props
    if len(favs) < n_ml:
        sys.exit(f"Only {len(favs)} FanDuel games available — can't build "
                 f"a parlay with {n_ml} moneyline legs.")

    prop_legs = []
    if n_props:
        cands, seen = [], set()
        for eid, matchup in events.items():
            cands.extend(fetch_fd_props(eid, matchup))
        cands.sort(key=lambda c: -c["p"])
        for c in cands:
            if c["player"] not in seen:
                seen.add(c["player"])
                prop_legs.append(c)
        if len(prop_legs) < n_props:
            sys.exit(f"Only {len(prop_legs)} priced FanDuel prop markets "
                     f"found — can't fill {n_props} prop legs.")
        prop_legs = prop_legs[:n_props]

    ml_legs = favs[:n_ml]
    combined = (prod(l["p"] for l in ml_legs)
                * prod(c["p"] for c in prop_legs))
    payout = args.stake / combined

    label = "MONEYLINE" if not n_props else "MONEYLINE + PROPS"
    print(f"\nSAFEST {args.legs}-LEG {label} PARLAY — FanDuel board "
          f"({len(favs)} games)")
    print("-" * 68)
    i = 0
    for i, l in enumerate(ml_legs, 1):
        print(f"  LEG {i}: {l['team']:<5} ML  ({l['matchup']:<12}) "
              f"{l['p']*100:5.1f}%  FD {_fmt_am(l['odds'])}")
    for i, c in enumerate(prop_legs, i + 1):
        side = "Ov" if c["side"] == "Over" else "Un"
        desc = f"{c['player']} {side} {c['line']:g} {c['type']}"
        print(f"  LEG {i}: {desc:<33} "
              f"{c['p']*100:5.1f}%  FD {_fmt_am(c['odds'])}")
    print("-" * 68)
    fd_pays = fd_posted_payout(args.stake, ml_legs + prop_legs)
    print(f"  COMBINED HIT PROBABILITY : {combined*100:.1f}%")
    print(f"  FAIR PARLAY PRICE        : {prob_to_american(combined)}")
    print(f"  ${args.stake:.0f} PAYS — fair          : ${payout:.2f}")
    print(f"  ${args.stake:.0f} PAYS — FD posted     : ${fd_pays:.2f}  "
          f"(vig costs ${payout - fd_pays:.2f})")
    print(f"\n  ONE-TAP TICKET — opens the FanDuel app with every leg "
          f"on the slip:")
    print(f"  {fd_ticket_url(ml_legs + prop_legs)}")
    print(f"\n  Probabilities are de-vigged from FanDuel's own prices. "
          f"Legs are treated\n  as independent; FanDuel reprices "
          f"same-game combos on the slip.")
    _print_target_check(args, combined, n_props)

    if args.target and combined < args.target:
        picks, achieved, avail = build_target_ticket(events, args.target,
                                                     args.legs, favs)
        if picks is None:
            best = (f"the safest {args.legs} games top out at "
                    f"{achieved*100:.1f}% combined" if achieved
                    else f"only {avail} games still have boards up")
            print(f"\n  Alternate lines can't get there either right now — "
                  f"{best}.")
        else:
            t_combined = achieved
            t_fd = fd_posted_payout(args.stake, picks)
            print(f"\n  BUT HERE'S A TICKET THAT DOES — "
                  f"{args.target*100:.0f}% target, alternate lines:")
            print("  " + "-" * 64)
            for i, p in enumerate(picks, 1):
                print(f"    LEG {i}: {p['desc']:<16} ({p['matchup']:<12}) "
                      f"{p['p']*100:5.1f}%  FD {_fmt_am(p['odds'])}")
            print("  " + "-" * 64)
            print(f"    COMBINED {t_combined*100:.1f}%  ·  "
                  f"${args.stake:.0f} pays ${t_fd:.2f} at posted odds "
                  f"(${t_fd - args.stake:.2f} profit)")
            print(f"    ONE-TAP: {fd_ticket_url(picks)}")
            print(f"    High-probability tickets pay pennies — "
                  f"that's the price of safety, not a flaw.")
    print("\n  Estimates, not guarantees. Nothing here is betting advice.\n")


def cmd_parlay(args, book=None):
    games = load_games(args)
    n_props = args.props
    if not 0 <= n_props <= args.legs:
        sys.exit(f"--props must be between 0 and --legs ({args.legs}).")
    n_ml = args.legs - n_props
    if len(games) < n_ml:
        sys.exit(f"Only {len(games)} games available — can't build "
                 f"a parlay with {n_ml} moneyline legs.")

    prop_legs = []
    if n_props:
        if args.demo:
            all_props = DEMO_PROPS
        else:
            try:
                all_props = []
                for e in fetch_bovada_events():
                    try:
                        all_props.extend(fetch_bovada_props(e["link"]))
                    except Exception:
                        continue  # one game's board down; use the rest
            except Exception as e:
                all_props = []
            if not all_props:
                sys.exit("Couldn't fetch prop prices from Bovada — "
                         "drop --props or try again later.")
        cands = prop_leg_candidates(all_props)
        if len(cands) < n_props:
            sys.exit(f"Only {len(cands)} priced prop markets found — "
                     f"can't fill {n_props} prop legs.")
        prop_legs = cands[:n_props]

    # Candidate legs = the favorite in every game.
    legs = []
    for g in games:
        if g["p_home"] >= g["p_away"]:
            fav, p, url = g["home"], g["p_home"], g.get("dk_home")
        else:
            fav, p, url = g["away"], g["p_away"], g.get("dk_away")
        legs.append({"team": fav, "matchup": f"{g['away']} @ {g['home']}",
                     "p": p, "url": url})

    # Safest combo of moneyline legs = the highest-probability favorites.
    best = ()
    if n_ml:
        best = max(combinations(legs, n_ml),
                   key=lambda c: prod(l["p"] for l in c))
    best = sorted(best, key=lambda l: -l["p"])
    combined = (prod(l["p"] for l in best)
                * prod(c["p"] for c in prop_legs))
    fair_dec = 1.0 / combined
    payout = args.stake * fair_dec

    label = "MONEYLINE" if not n_props else "MONEYLINE + PROPS"
    print(f"\nSAFEST {args.legs}-LEG {label} PARLAY "
          f"({len(games)} games on the board)")
    print("-" * 68)
    n = 0
    for n, l in enumerate(best, 1):
        print(f"  LEG {n}: {l['team']:<5} ML  ({l['matchup']:<21}) "
              f"{l['p']*100:5.1f}%  fair {prob_to_american(l['p'])}")
    for i, c in enumerate(prop_legs, n + 1):
        side = "Ov" if c["side"] == "Over" else "Un"
        desc = (f"{c['player']} ({c['team']}) {side} {c['line']:g} "
                f"{SHORT_PROP.get(c['type'], c['type'])}")
        print(f"  LEG {i}: {desc:<33} "
              f"{c['p']*100:5.1f}%  fair {prob_to_american(c['p'])}")
    print("-" * 68)
    print(f"  COMBINED HIT PROBABILITY : {combined*100:.1f}%")
    print(f"  FAIR PARLAY PRICE        : {prob_to_american(combined)}"
          f"  (books pay less after vig)")
    print(f"  ${args.stake:.0f} RETURNS (fair)      : "
          f"${payout:.2f}  (${payout - args.stake:.2f} profit)")

    if n_props:
        print(f"\n  Prop legs are the safest priced sides on Bovada's board"
              f"\n  (alternate lines included), de-vigged like everything"
              f"\n  else. Legs are treated as independent: books price"
              f"\n  same-game combos differently and may bar some entirely.")

    if any(l["url"] for l in best) or any(c["url"] for c in prop_legs):
        print(f"\n  BET LINKS")
        if any(l["url"] for l in best):
            print(f"  DraftKings keeps your slip as you tap each leg in turn:")
            for l in best:
                print(f"    {l['team']:<4} ML  {l['url'] or '(no link posted)'}")
        if any(c["url"] for c in prop_legs):
            print(f"  Prop links open the game's Bovada board — "
                  f"tap your side there:")
            for c in prop_legs:
                if c["url"]:
                    print(f"    {c['player']} {c['side']} {c['line']:g}  "
                          f"{c['url']}")
        print(f"  (One tap for a whole cross-book ticket isn't possible "
              f"without a book's partner API.)")
    elif args.demo:
        print(f"\n  Bet links appear in live mode.")

    _print_target_check(args, combined, n_props)
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
    pp.add_argument("--book", choices=["fd", "espn"], default="fd",
                    help="fd (default): FanDuel board with a one-tap "
                         "bet-slip link; espn: ESPN/Bovada with "
                         "per-leg links")
    pp.add_argument("--pay", type=int, default=None, metavar="+500",
                    help="build the most likely ticket paying at least "
                         "these American odds (e.g. 500 or -150); "
                         "overrides the safest-ticket flow")

    pr = sub.add_parser("props", parents=[common],
                        help="list player prop lines for a team's next game")
    pr.add_argument("team", nargs="?", default="",
                    help="team abbreviation, e.g. DEN (any team in the game)")
    pr.add_argument("--type", choices=sorted(PROP_FILTERS),
                    help="filter: pass, rush, rec, td, or all "
                         "(default: the core yardage/receptions props)")
    pr.add_argument("--limit", type=int, default=20,
                    help="max props to show (default 20)")
    pr.add_argument("--alts", action="store_true",
                    help="show every alternate line, not just the main one")
    pr.add_argument("--source", choices=["auto", "bovada", "espn"],
                    default="auto",
                    help="odds source (default auto: Bovada prices, "
                         "ESPN lines as fallback)")

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
        if args.book == "fd" and not args.demo:
            cmd_parlay_fd(args)
        else:
            cmd_parlay(args)


if __name__ == "__main__":
    main()
