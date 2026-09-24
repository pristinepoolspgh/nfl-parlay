#!/usr/bin/env python3
"""Build the Parlay Board page from live FanDuel + ESPN data.

Usage:  python3 board/make_snapshot.py [output.html]

Fetches the current FanDuel NFL board (both moneyline sides, top-14
priced props, per-game alternate-line pareto frontiers) and ESPN's
week number and in-progress scores, then splices the data into
board/template.html. Fetches go through curl so it also works behind
proxies that filter user agents.
"""
import html as htmllib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import nfl_parlay as np


def curl_json(url):
    out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                         capture_output=True, check=True)
    return json.loads(out.stdout)


np._get_json = curl_json


INJ_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
           "injuries")
POS_RANK = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}

ROTO_URL = "https://www.rotowire.com/football/news.php"
ROTO_ABBR = {"WAS": "WSH", "JAC": "JAX", "LA": "LAR", "ARZ": "ARI"}


def fetch_rotowire():
    """Rotowire's NFL news feed: team-tagged player items that relay
    beat-writer and insider reporting (often X-sourced) minutes after
    it breaks — practice participation, injuries, role changes. Team
    comes from the logo, player and headline from the item itself."""
    by_team = {}
    try:
        out = subprocess.run(["curl", "-sSgL", "--max-time", "25",
                              ROTO_URL],
                             capture_output=True, check=True)
        text = out.stdout.decode("utf-8", "replace")
    except Exception:
        return by_team
    pat = re.compile(
        r'news-update__logo" src="[^"]*?/([A-Z]{2,3})\.svg[^>]*>.*?'
        r'news-update__player-link"[^>]*>([^<]+)</a>.*?'
        r'news-update__headline"[^>]*>([^<]+)</a>', re.S)
    for ab, player, head in pat.findall(text):
        ab = ROTO_ABBR.get(ab, ab)
        rows = by_team.setdefault(ab, [])
        h = (f"{htmllib.unescape(player).strip()}: "
             f"{htmllib.unescape(head).strip()}")
        if h not in rows and len(rows) < 3:
            rows.append(h)
    return by_team


NFL_NEWS_URL = "https://www.nfl.com/news/"
NICKNAMES = {
    "Cardinals": "ARI", "Falcons": "ATL", "Ravens": "BAL", "Bills": "BUF",
    "Panthers": "CAR", "Bears": "CHI", "Bengals": "CIN", "Browns": "CLE",
    "Cowboys": "DAL", "Broncos": "DEN", "Lions": "DET", "Packers": "GB",
    "Texans": "HOU", "Colts": "IND", "Jaguars": "JAX", "Chiefs": "KC",
    "Raiders": "LV", "Chargers": "LAC", "Rams": "LAR", "Dolphins": "MIA",
    "Vikings": "MIN", "Patriots": "NE", "Saints": "NO", "Giants": "NYG",
    "Jets": "NYJ", "Eagles": "PHI", "Steelers": "PIT", "49ers": "SF",
    "Seahawks": "SEA", "Buccaneers": "TB", "Titans": "TEN",
    "Commanders": "WSH"}


def fetch_nfl_news():
    """Recent NFL.com headlines keyed by team abbreviation. The site
    has no public JSON feed, but every article card carries an
    accessible label with headline + publish date; team-tag by
    nickname match and keep the last few days only."""
    by_team = {}
    try:
        out = subprocess.run(["curl", "-sSgL", "--max-time", "25",
                              NFL_NEWS_URL],
                             capture_output=True, check=True)
        text = out.stdout.decode("utf-8", "replace")
    except Exception:
        return by_team
    cutoff = datetime.utcnow() - timedelta(days=5)
    for m in re.finditer(r'aria-label="(?:[a-z]+ - )?Read article: '
                         r'([^"]+), ([A-Z][a-z]+ \d{1,2}, \d{4})"', text):
        head = htmllib.unescape(m.group(1)).strip()
        try:
            when = datetime.strptime(m.group(2), "%B %d, %Y")
        except ValueError:
            continue
        if when < cutoff:
            continue
        for nick, ab in NICKNAMES.items():
            if nick in head:
                rows = by_team.setdefault(ab, [])
                if head not in rows and len(rows) < 3:
                    rows.append(head)
    return by_team


PW_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
          "stats_player/stats_player_week_{season}.csv")


def fetch_qb_starters(season):
    """(starters, qb_team): each team's usual QB — the season pass-
    attempt leader per nflverse — and a name→team map for every QB
    who has thrown. Data, not memory: keeps the QB-change dock from
    firing on a hurt backup, and lets FanDuel's prop-implied starter
    reveal a change the injury report doesn't."""
    import csv
    import io
    alias = {"WAS": "WSH", "LA": "LAR", "JAC": "JAX", "ARZ": "ARI"}
    try:
        out = subprocess.run(["curl", "-sSgL", "--max-time", "30",
                              PW_URL.format(season=season)],
                             capture_output=True, check=True)
        rows = csv.DictReader(io.StringIO(out.stdout.decode()))
    except Exception:
        return {}, {}
    att, qb_team = {}, {}
    for r in rows:
        if (r.get("position") != "QB"
                or r.get("season_type", "REG") != "REG"):
            continue
        t = alias.get(r["team"], r["team"])
        n = r.get("player_display_name", "")
        try:
            a = int(float(r.get("attempts") or 0))
        except ValueError:
            continue
        att.setdefault(t, {})
        att[t][n] = att[t].get(n, 0) + a
        if n:
            qb_team[_norm_name(n)] = t
    return ({t: max(qbs, key=qbs.get) for t, qbs in att.items() if qbs},
            qb_team)


TD_TAB = ("https://sbapi.pa.sportsbook.fanduel.com/api/event-page"
          "?_ak=FhMFpcPWXMeyZxOx&eventId={eid}&tab=td-scorer-props")


NEWS_URL = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/"
            "news?limit=50")


def fetch_news():
    """Recent ESPN headlines keyed by team abbreviation. Headlines are
    reported news, attached verbatim — the board and the reads cite
    them as reporting, never as their own knowledge."""
    by_team = {}
    try:
        d = curl_json(NEWS_URL)
    except Exception:
        return by_team
    for a in d.get("articles", []):
        head = a.get("headline", "").strip()
        if not head:
            continue
        for c in a.get("categories", []):
            t = (c.get("team") or {}).get("description")
            if not t:
                continue
            ab = np._abbr(t)
            rows = by_team.setdefault(ab, [])
            if head not in rows and len(rows) < 3:
                rows.append(head)
    return by_team


def fetch_tds(eid, mu, top=5):
    """Any Time Touchdown Scorer runners for one game. A one-sided
    market: there is no opposite side to de-vig against, so `p` is the
    implied probability with FanDuel's vig still in it — the board
    labels it as such rather than pretending it's fair.
    """
    d = curl_json(TD_TAB.format(eid=eid))
    for m in d.get("attachments", {}).get("markets", {}).values():
        if (m.get("marketName") != "Any Time Touchdown Scorer"
                or m.get("marketStatus") != "OPEN"):
            continue
        rows = []
        for r in m.get("runners", []):
            if r.get("runnerStatus") != "ACTIVE":
                continue
            o = np._fd_odds(r)
            if o is None:
                continue
            rows.append({"player": r["runnerName"], "matchup": mu,
                         "p": round(np.american_to_prob(o), 5),
                         "odds": o, "market": m["marketId"],
                         "sel": r["selectionId"]})
        rows.sort(key=lambda r: -r["p"])
        return rows[:top]
    return []

WX_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}"
          "&longitude={lon}&hourly=temperature_2m,precipitation_probability,"
          "wind_speed_10m,wind_gusts_10m&temperature_unit=fahrenheit"
          "&wind_speed_unit=mph&timezone=America%2FNew_York&forecast_days=3")

# Home stadium per team: (lat, lon, roof). Weather only matters outdoors;
# retractables usually close in bad weather but the forecast still informs.
STADIUMS = {
    "ARI": (33.5276, -112.2626, "retract"),
    "ATL": (33.7554, -84.4010, "retract"),
    "BAL": (39.2780, -76.6227, "open"),
    "BUF": (42.7738, -78.7870, "open"),
    "CAR": (35.2258, -80.8528, "open"),
    "CHI": (41.8623, -87.6167, "open"),
    "CIN": (39.0955, -84.5161, "open"),
    "CLE": (41.5061, -81.6995, "open"),
    "DAL": (32.7473, -97.0945, "retract"),
    "DEN": (39.7439, -105.0201, "open"),
    "DET": (42.3400, -83.0456, "dome"),
    "GB": (44.5013, -88.0622, "open"),
    "HOU": (29.6847, -95.4107, "retract"),
    "IND": (39.7601, -86.1639, "retract"),
    "JAX": (30.3239, -81.6373, "open"),
    "KC": (39.0489, -94.4839, "open"),
    "LAC": (33.9535, -118.3392, "dome"),
    "LAR": (33.9535, -118.3392, "dome"),
    "LV": (36.0909, -115.1833, "dome"),
    "MIA": (25.9580, -80.2389, "open"),
    "MIN": (44.9736, -93.2575, "dome"),
    "NE": (42.0909, -71.2643, "open"),
    "NO": (29.9511, -90.0812, "dome"),
    "NYG": (40.8135, -74.0745, "open"),
    "NYJ": (40.8135, -74.0745, "open"),
    "PHI": (39.9008, -75.1675, "open"),
    "PIT": (40.4468, -80.0158, "open"),
    "SEA": (47.5952, -122.3316, "open"),
    "SF": (37.4030, -121.9700, "open"),
    "TB": (27.9759, -82.5033, "open"),
    "TEN": (36.1665, -86.7713, "open"),
    "WSH": (38.9078, -76.8645, "open"),
}


def fetch_weather(home_team, start_et):
    """Kickoff-hour forecast at the home stadium (times are ET)."""
    stad = STADIUMS.get(home_team)
    if not stad:
        return None
    lat, lon, roof = stad
    if roof == "dome":
        return {"roof": "dome"}
    try:
        d = curl_json(WX_URL.format(lat=lat, lon=lon))
        h = d["hourly"]
        want = start_et[:13].replace(" ", "T") + ":00"
        i = h["time"].index(want)
        return {"roof": roof,
                "temp": round(h["temperature_2m"][i]),
                "wind": round(h["wind_speed_10m"][i]),
                "gust": round(h["wind_gusts_10m"][i]),
                "pop": h["precipitation_probability"][i]}
    except Exception:
        return {"roof": roof}


def _norm_name(n):
    toks = [t for t in n.lower().replace(".", "").split()
            if t not in ("jr", "sr", "ii", "iii", "iv", "v")]
    return " ".join(toks)


def fetch_injuries():
    """{team_abbr: [{name, pos, status}]} for Out/Doubtful/Questionable."""
    by_team = {}
    try:
        d = curl_json(INJ_URL)
    except Exception:
        return by_team
    for t in d.get("injuries", []):
        rows = []
        for inj in t.get("injuries", []):
            st = inj.get("status")
            if st not in ("Out", "Doubtful", "Questionable"):
                continue
            a = inj.get("athlete", {})
            rows.append({"name": a.get("displayName", ""),
                         "pos": (a.get("position") or {})
                         .get("abbreviation", ""),
                         "status": st})
        rows.sort(key=lambda r: (POS_RANK.get(r["pos"], 9),
                                 r["status"] != "Out"))
        by_team[np._abbr(t.get("displayName", ""))] = rows
    return by_team


def build_snapshot():
    espn = curl_json(np.ESPN_URL)
    week = espn.get("week", {}).get("number")
    scores = []
    for ev in espn.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = comp.get("status", {}).get("type", {})
        if st.get("state") not in ("in", "post"):
            continue
        t = {c["homeAway"]: c for c in comp.get("competitors", [])}
        scores.append({
            "matchup": ev.get("shortName", ""),
            "away": f"{t['away']['team']['abbreviation']} "
                    f"{t['away'].get('score', '0')}",
            "home": f"{t['home']['team']['abbreviation']} "
                    f"{t['home'].get('score', '0')}",
            "detail": st.get("shortDetail", ""),
            "final": st.get("state") == "post"})

    page = curl_json(np.FD_PAGE)
    att = page["attachments"]
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    events = {}
    for eid, ev in att["events"].items():
        name = ev.get("name", "")
        if " @ " not in name or ev.get("openDate", "")[:19] <= now:
            continue
        away, home = name.split(" @ ", 1)
        events[int(eid)] = {
            "matchup": f"{np._abbr(away)} @ {np._abbr(home)}",
            "start": np._kickoff_et(ev["openDate"][:16] + "Z")}

    # FanDuel opens next week's lines while this week is still ahead;
    # keep the board to ESPN's current week so two slates don't mix.
    # (ESPN writes neutral-site games as "A VS B".) If the join comes
    # up empty — e.g. late Monday before ESPN flips the week — show
    # everything rather than a blank board.
    week_mus = {ev.get("shortName", "").replace(" VS ", " @ ")
                for ev in espn.get("events", [])}
    in_week = {eid: e for eid, e in events.items()
               if e["matchup"] in week_mus}
    if in_week:
        events = in_week

    games = []
    for m in att["markets"].values():
        if (m.get("marketType") != "MONEY_LINE"
                or m.get("marketStatus") != "OPEN"
                or m.get("eventId") not in events):
            continue
        rs = [r for r in m.get("runners", [])
              if r.get("runnerStatus") == "ACTIVE"
              and np._fd_odds(r) is not None]
        if len(rs) != 2:
            continue
        pa, pb = np.devig(np.american_to_prob(np._fd_odds(rs[0])),
                          np.american_to_prob(np._fd_odds(rs[1])))
        sides = sorted([
            {"team": np._abbr(rs[0]["runnerName"]), "p": round(pa, 5),
             "odds": np._fd_odds(rs[0]), "sel": rs[0]["selectionId"]},
            {"team": np._abbr(rs[1]["runnerName"]), "p": round(pb, 5),
             "odds": np._fd_odds(rs[1]), "sel": rs[1]["selectionId"]},
        ], key=lambda s: -s["p"])
        e = events[m["eventId"]]
        games.append({"matchup": e["matchup"], "start": e["start"],
                      "market": m["marketId"], "sides": sides})
    games.sort(key=lambda g: -g["sides"][0]["p"])

    # Live in-play markets (ML / spread / total) for started games.
    started = {}
    for eid, ev in att["events"].items():
        name = ev.get("name", "")
        if " @ " in name and ev.get("openDate", "")[:19] <= now:
            away, home = name.split(" @ ", 1)
            started[int(eid)] = f"{np._abbr(away)} @ {np._abbr(home)}"
    final_mus = {s["matchup"] for s in scores if s["final"]}
    korder = {"ml": 0, "spread": 1, "total": 2, "td": 3}
    live = {}
    for m in att["markets"].values():
        mu = started.get(m.get("eventId"))
        if (not mu or mu in final_mus
                or m.get("marketStatus") != "OPEN"
                or m.get("marketType") not in
                ("MONEY_LINE", "MATCH_HANDICAP_(2-WAY)",
                 "TOTAL_POINTS_(OVER/UNDER)")):
            continue
        rs = [r for r in m.get("runners", [])
              if r.get("runnerStatus") == "ACTIVE"
              and np._fd_odds(r) is not None]
        if len(rs) != 2:
            continue
        pa, pb = np.devig(np.american_to_prob(np._fd_odds(rs[0])),
                          np.american_to_prob(np._fd_odds(rs[1])))
        for r, p in ((rs[0], pa), (rs[1], pb)):
            nm, h = r.get("runnerName", ""), float(r.get("handicap") or 0)
            mt = m["marketType"]
            if mt == "MONEY_LINE":
                desc, kind = f"{np._abbr(nm)} ML", "ml"
            elif mt == "MATCH_HANDICAP_(2-WAY)":
                desc, kind = f"{np._abbr(nm)} {h:+g}", "spread"
            else:
                side = "Over" if nm.startswith("Over") else "Under"
                desc, kind = f"{side} {abs(h):g} pts", "total"
            live.setdefault(mu, []).append(
                {"desc": desc, "kind": kind, "p": round(p, 5),
                 "odds": np._fd_odds(r), "market": m["marketId"],
                 "sel": r["selectionId"]})
    # In-play TD odds: who's still priced to score in a live game.
    for eid, mu in started.items():
        if mu in final_mus:
            continue
        try:
            for r in fetch_tds(eid, mu, top=4):
                live.setdefault(mu, []).append(
                    {"desc": f"{r['player']} TD", "kind": "td",
                     "p": r["p"], "odds": r["odds"],
                     "market": r["market"], "sel": r["sel"]})
        except Exception:
            pass
    for mu in live:
        live[mu].sort(key=lambda b: korder[b["kind"]])

    cands, seen, props, alts, tds = [], set(), [], {}, []
    for eid, e in events.items():
        mu = e["matchup"]
        cands.extend(np.fetch_fd_props(eid, mu))
        try:
            tds.extend(fetch_tds(eid, mu))
        except Exception:
            pass
        rungs = [a for a in np.fetch_fd_alts(eid, mu) if a["p"] >= 0.02]
        g = next((x for x in games if x["matchup"] == mu), None)
        if g:
            for s in g["sides"]:
                rungs.append({"desc": s["team"] + " ML", "p": s["p"],
                              "odds": s["odds"], "market": g["market"],
                              "sel": s["sel"], "matchup": mu})
        # Keep the pareto frontier: rising payout as probability falls.
        rungs.sort(key=lambda a: (-a["p"], -np.fd_decimal(a["odds"])))
        front, bestdec = [], 0
        for a in rungs:
            d = np.fd_decimal(a["odds"])
            if d > bestdec:
                front.append({"desc": a["desc"], "p": round(a["p"], 5),
                              "odds": a["odds"], "market": a["market"],
                              "sel": a["sel"]})
                bestdec = d
        front.reverse()
        alts[mu] = front
    cands.sort(key=lambda c: -c["p"])
    for c in cands:
        if c["player"] not in seen:
            seen.add(c["player"])
            c["p"] = round(c["p"], 5)
            props.append(c)

    # Availability, news, weather — fetched BEFORE the model so it can
    # weigh them; attached to the game cards here too.
    inj_by_team = fetch_injuries()
    news_by_team = fetch_news()
    for extra in (fetch_rotowire, fetch_nfl_news):
        for ab, heads in extra().items():
            rows = news_by_team.setdefault(ab, [])
            for h in heads:
                if h not in rows and len(rows) < 3:
                    rows.append(h)
    status_by_name = {_norm_name(r["name"]): r["status"]
                      for rows in inj_by_team.values() for r in rows}
    starters, qb_team = fetch_qb_starters(datetime.utcnow().year)
    # FanDuel's passing props imply who actually starts — the book
    # prices the real QB before injury reports catch up, and it also
    # catches benchings the report never lists.
    implied_qbs = {}
    for c in cands:
        if "Passing" in (c.get("type") or ""):
            implied_qbs.setdefault(c["matchup"], set()).add(
                _norm_name(c["player"]))
    for g in games:
        away, home = g["matchup"].split(" @ ")
        g["inj"] = {t: inj_by_team.get(t, [])[:4] for t in (away, home)
                    if inj_by_team.get(t)}
        heads = [h for t in (away, home)
                 for h in news_by_team.get(t, [])[:2]]
        if heads:
            g["news"] = heads[:3]
        wx = fetch_weather(home, g["start"])
        if wx:
            g["wx"] = wx

    QB_DOCK = 4.0  # validated on 793 changed-starter games, 2015-2026
    #                (board/tune.py: docks 1-5 all beat none, 4.0 best)
    #                WEEKS 2-4 FAILED validation (250 games: every dock
    #                graded worse — early changes are mostly planned
    #                and already priced), so the dock is gated to wk 5+.

    def qb_dock(team, mu):
        """Dock a team starting someone other than its usual QB (the
        season pass-attempt leader per nflverse). Two triggers: the
        usual starter is injury-listed Out/Doubtful, or FanDuel's
        passing props for the game imply a different QB for this team
        — which catches benchings and unlisted changes. A hurt backup
        never triggers it; Questionable alone stays the read's call.
        Gated to week 5+: the only regime where the backtest validates
        it. Earlier weeks leave QB changes to the read's judgment."""
        qb = starters.get(team)
        if not qb or (week or 0) < 5:
            return 0.0
        for r in inj_by_team.get(team, []):
            if (r["pos"] == "QB" and r["status"] in ("Out", "Doubtful")
                    and _norm_name(r["name"]) == _norm_name(qb)):
                return QB_DOCK
        implied = implied_qbs.get(mu, set())
        mine = {q for q in implied if qb_team.get(q) == team}
        if mine and _norm_name(qb) not in mine:
            return QB_DOCK
        return 0.0

    def wx_shift(g):
        """Wind and rain press totals outdoors; domes exempt, and a
        retractable is assumed closed in bad weather."""
        w = g.get("wx") or {}
        if w.get("roof") != "open" or w.get("wind") is None:
            return 0.0
        s = 0.0
        if w["wind"] >= 15:
            s -= min(0.3 * (w["wind"] - 10), 6.0)
        if (w.get("pop") or 0) >= 60:
            s -= 1.0
        return round(s, 1)

    simbets = []
    # Model layer: run the simulator on each game — projected score,
    # win probability, and the prediction log that grades the model.
    elo_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "memory", "elo.json")
    if os.path.exists(elo_path):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import sim as simmod
        model = simmod.Model(elo_path)
        simlog_path = os.path.join(os.path.dirname(elo_path),
                                   "simlog.jsonl")
        logged = set()
        if os.path.exists(simlog_path):
            for line in open(simlog_path):
                try:
                    r = json.loads(line)
                    logged.add((r["date"], r["matchup"]))
                except Exception:
                    continue
        with open(simlog_path, "a") as slf:
            for g in games:
                away, home = g["matchup"].split(" @ ")
                mu = g["matchup"]
                dh, da, ts = (qb_dock(home, mu), qb_dock(away, mu),
                              wx_shift(g))
                pred = model.predict(home, away, dock_home=dh,
                                     dock_away=da, total_shift=ts)
                if dh or da or ts:
                    g["adj"] = {"dock": {t: p for t, p in
                                         ((home, dh), (away, da)) if p},
                                "wx": ts}
                fav = g["sides"][0]["team"]
                g["ep"] = (pred["p_home"] if fav == home
                           else round(1.0 - pred["p_home"], 4))
                g["proj"] = {"h": round(pred["proj"]["home"]),
                             "a": round(pred["proj"]["away"])}
                # Sim-price every alt rung of this game so the ticket
                # builders can hear the model when choosing legs.
                mu_m, mu_t = pred["mu_margin"], pred["mu_total"]
                for r in alts.get(g["matchup"], []):
                    desc = r.get("desc", "")
                    m_tot = re.match(r"^(Over|Under) ([\d.]+) pts$", desc)
                    m_spr = re.match(r"^([A-Z]{2,3}) ([+-][\d.]+)$", desc)
                    m_ml = re.match(r"^([A-Z]{2,3}) ML$", desc)
                    sp = None
                    if m_tot:
                        po = model.p_over(mu_t, float(m_tot.group(2)))
                        sp = po if m_tot.group(1) == "Over" else 1.0 - po
                    elif m_spr:
                        team, ln = m_spr.group(1), float(m_spr.group(2))
                        if team == home:
                            sp = model.p_cover(mu_m, ln)
                        elif team == away:
                            sp = 1.0 - model.p_cover(mu_m, -ln)
                    elif m_ml:
                        if m_ml.group(1) == home:
                            sp = pred["p_home"]
                        elif m_ml.group(1) == away:
                            sp = 1.0 - pred["p_home"]
                    if sp is not None:
                        r["sp"] = round(sp, 4)
                key = (g["start"][:10], g["matchup"])
                if key not in logged:
                    slf.write(json.dumps({
                        "date": key[0], "matchup": g["matchup"],
                        "week": week, "mu_margin": pred["mu_margin"],
                        "mu_total": pred["mu_total"],
                        "p_home": pred["p_home"],
                        "v": getattr(simmod.Model, "VERSION", 1)}) + "\n")
                    logged.add(key)

        # The sims' strongest calls: rungs where the model's own price
        # beats the market's by the most. Shown, tappable, and honest
        # about the record — the closing line usually wins this
        # argument (docs/backtests.md), so these are the exceptions
        # the model insists on, not gospel.
        for g in games:
            cand = [r for r in alts.get(g["matchup"], [])
                    if "sp" in r and r["p"] >= 0.2
                    and r["sp"] - r["p"] >= 0.05]
            cand.sort(key=lambda r: r["p"] - r["sp"])
            for r in cand[:2]:
                simbets.append({**r, "matchup": g["matchup"]})
        simbets.sort(key=lambda r: r["p"] - r["sp"])
        simbets = simbets[:10]

    # Closing-line log: keep the latest pregame sighting per game (CLV).
    close_path = os.path.join(os.path.dirname(elo_path), "close.jsonl")
    closes = {}
    if os.path.exists(close_path):
        for line in open(close_path):
            try:
                r = json.loads(line)
                closes[(r["date"], r["matchup"])] = r
            except Exception:
                continue
    stamp_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    for g in games:
        fav = g["sides"][0]
        closes[(g["start"][:10], g["matchup"])] = {
            "date": g["start"][:10], "matchup": g["matchup"],
            "fav": fav["team"], "p_fav": fav["p"], "odds": fav["odds"],
            "seen": stamp_utc}
    with open(close_path, "w") as f:
        for r in closes.values():
            f.write(json.dumps(r) + "\n")

    # Tag injured players on props and TD scorers.
    for c in props:
        st = status_by_name.get(_norm_name(c["player"]))
        if st:
            c["inj"] = st
    tds.sort(key=lambda r: -r["p"])
    tds = tds[:20]
    for c in tds:
        st = status_by_name.get(_norm_name(c["player"]))
        if st:
            c["inj"] = st

    # Plain-English model notes: say what each flagged edge means, and
    # dismiss the ones the injury report explains (Elo can't see hurt QBs).
    def _qb_hurt(team):
        return any(r["pos"] == "QB" and r["status"] in ("Out", "Doubtful")
                   for r in inj_by_team.get(team, []))
    for g in games:
        if "ep" not in g:
            continue
        fav, dog = g["sides"][0]["team"], g["sides"][1]["team"]
        m, e = g["sides"][0]["p"], g["ep"]
        edge = e - m
        if abs(edge) < 0.04:
            continue
        mp, epc = f"{m*100:.0f}%", f"{e*100:.0f}%"
        proj = g.get("proj")
        away_t, home_t = g["matchup"].split(" @ ")
        ps = (f"Sims see {home_t} {proj['h']}\u2013{proj['a']} {away_t}. "
              if proj else "")
        docked = set(((g.get("adj") or {}).get("dock") or {}))
        if edge < 0 and _qb_hurt(dog) and dog not in docked:
            g["say"] = (ps + f"Our numbers only make {fav} {epc}, but the market's "
                        f"{mp} knows {dog}'s QB is hurt — gap explained, "
                        f"no edge.")
            g["sayx"] = True
        elif edge > 0 and _qb_hurt(fav) and fav not in docked:
            g["say"] = (ps + f"Our numbers like {fav} at {epc} vs the market's "
                        f"{mp}, but {fav}'s QB injury explains the market's "
                        f"caution.")
            g["sayx"] = True
        elif edge < 0:
            g["say"] = (ps + f"The price says {fav} {mp}; their results say "
                        f"more like {epc}. Either the number is rich — or "
                        f"the market knows something the scores don't.")
        else:
            g["say"] = (ps + f"{fav} have played better than this price: our "
                        f"numbers say {epc}, the market only {mp}. Value on "
                        f"{fav} unless there's news the scores can't see.")

    # Say what the model already weighed, so nobody double-counts it.
    for g in games:
        adj = g.get("adj") or {}
        bits = [f"sims dock {t} {p:g} pts (QB change)"
                for t, p in (adj.get("dock") or {}).items()]
        if adj.get("wx"):
            bits.append(f"weather trims the total {abs(adj['wx']):g} pts")
        if bits:
            extra = "Already in the sims: " + "; ".join(bits) + "."
            if g.get("say"):
                g["say"] += " " + extra
            else:
                g["say"], g["sayx"] = extra, True

    stamp = (datetime.now(np._EASTERN) if np._EASTERN
             else datetime.utcnow()).strftime("%b %d, %Y %I:%M %p ET")
    return {"generated": stamp, "week": week, "games": games,
            "props": props[:24], "tds": tds, "alts": alts,
            "simbets": simbets, "scores": scores, "live": live}


def log_pregame(snap):
    """Append each game's pregame favorite line to memory/pregame.jsonl,
    once per (kickoff date, matchup) — the raw material for calibration.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "memory", "pregame.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                r = json.loads(line)
                seen.add((r["date"], r["matchup"]))
            except Exception:
                continue
    added = 0
    with open(path, "a") as f:
        for g in snap["games"]:
            date = g["start"][:10]
            if (date, g["matchup"]) in seen:
                continue
            fav = g["sides"][0]
            f.write(json.dumps({
                "date": date, "week": snap["week"],
                "matchup": g["matchup"], "fav": fav["team"],
                "p_fav": fav["p"], "odds": fav["odds"],
                "source": "fanduel"}) + "\n")
            added += 1
    return added


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "parlay-board.html"
    snap = build_snapshot()
    logged = log_pregame(snap)
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "template.html")
    tpl = open(tpl_path).read()
    assert "/*__DATA__*/" in tpl, "template placeholder missing"
    html = tpl.replace("/*__DATA__*/",
                       json.dumps(snap, separators=(",", ":")), 1)
    open(out, "w").write(html)
    print(f"{out}: {len(snap['games'])} games, {len(snap['props'])} props, "
          f"{sum(len(v) for v in snap['alts'].values())} alt rungs, "
          f"{len(snap['scores'])} scores, week {snap['week']}, "
          f"{logged} new pregame lines logged, as of {snap['generated']}")


if __name__ == "__main__":
    main()
