#!/usr/bin/env python3
"""Build the Parlay Board page from live FanDuel + ESPN data.

Usage:  python3 board/make_snapshot.py [output.html]

Fetches the current FanDuel NFL board (both moneyline sides, top-14
priced props, per-game alternate-line pareto frontiers) and ESPN's
week number and in-progress scores, then splices the data into
board/template.html. Fetches go through curl so it also works behind
proxies that filter user agents.
"""
import json
import os
import subprocess
import sys
from datetime import datetime

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
    korder = {"ml": 0, "spread": 1, "total": 2}
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
    for mu in live:
        live[mu].sort(key=lambda b: korder[b["kind"]])

    cands, seen, props, alts = [], set(), [], {}
    for eid, e in events.items():
        mu = e["matchup"]
        cands.extend(np.fetch_fd_props(eid, mu))
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

    # Model layer: attach Elo win probability for each game's favorite.
    elo_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "memory", "elo.json")
    if os.path.exists(elo_path):
        ratings = json.load(open(elo_path)).get("ratings", {})
        for g in games:
            away, home = g["matchup"].split(" @ ")
            ra = ratings.get(home, 1500.0) + 48.0
            ph = 1.0 / (1.0 + 10 ** (-(ra - ratings.get(away, 1500.0)) / 400.0))
            fav = g["sides"][0]["team"]
            g["ep"] = round(ph if fav == home else 1.0 - ph, 4)

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

    # Injury layer: attach key injuries per game, tag injured prop players.
    inj_by_team = fetch_injuries()
    status_by_name = {_norm_name(r["name"]): r["status"]
                      for rows in inj_by_team.values() for r in rows}
    for g in games:
        away, home = g["matchup"].split(" @ ")
        g["inj"] = {t: inj_by_team.get(t, [])[:4] for t in (away, home)
                    if inj_by_team.get(t)}
        wx = fetch_weather(home, g["start"])
        if wx:
            g["wx"] = wx
    for c in props:
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
        if edge < 0 and _qb_hurt(dog):
            g["say"] = (f"Our numbers only make {fav} {epc}, but the market's "
                        f"{mp} knows {dog}'s QB is hurt — gap explained, "
                        f"no edge.")
            g["sayx"] = True
        elif edge > 0 and _qb_hurt(fav):
            g["say"] = (f"Our numbers like {fav} at {epc} vs the market's "
                        f"{mp}, but {fav}'s QB injury explains the market's "
                        f"caution.")
            g["sayx"] = True
        elif edge < 0:
            g["say"] = (f"The price says {fav} {mp}; their results say "
                        f"more like {epc}. Either the number is rich — or "
                        f"the market knows something the scores don't.")
        else:
            g["say"] = (f"{fav} have played better than this price: our "
                        f"numbers say {epc}, the market only {mp}. Value on "
                        f"{fav} unless there's news the scores can't see.")

    stamp = (datetime.now(np._EASTERN) if np._EASTERN
             else datetime.utcnow()).strftime("%b %d, %Y %I:%M %p ET")
    return {"generated": stamp, "week": week, "games": games,
            "props": props[:24], "alts": alts, "scores": scores,
            "live": live}


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
