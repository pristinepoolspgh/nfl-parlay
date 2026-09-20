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

    cands, seen, props, alts = [], set(), [], {}
    for eid, e in events.items():
        mu = e["matchup"]
        cands.extend(np.fetch_fd_props(eid, mu))
        rungs = [a for a in np.fetch_fd_alts(eid, mu) if a["p"] >= 0.60]
        g = next((x for x in games if x["matchup"] == mu), None)
        if g:
            f = g["sides"][0]
            rungs.append({"desc": f["team"] + " ML", "p": f["p"],
                          "odds": f["odds"], "market": g["market"],
                          "sel": f["sel"], "matchup": mu})
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

    # Injury layer: attach key injuries per game, tag injured prop players.
    inj_by_team = fetch_injuries()
    status_by_name = {_norm_name(r["name"]): r["status"]
                      for rows in inj_by_team.values() for r in rows}
    for g in games:
        away, home = g["matchup"].split(" @ ")
        g["inj"] = {t: inj_by_team.get(t, [])[:4] for t in (away, home)
                    if inj_by_team.get(t)}
    for c in props:
        st = status_by_name.get(_norm_name(c["player"]))
        if st:
            c["inj"] = st

    stamp = (datetime.now(np._EASTERN) if np._EASTERN
             else datetime.utcnow()).strftime("%b %d, %Y %I:%M %p ET")
    return {"generated": stamp, "week": week, "games": games,
            "props": props[:14], "alts": alts, "scores": scores}


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
