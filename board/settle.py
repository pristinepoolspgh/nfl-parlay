#!/usr/bin/env python3
"""Grade pending Parlay Board tickets against ESPN final scores.

Usage:  python3 board/settle.py tickets.json > updates.json

stdin/file: a JSON array of {"id": <doc id>, "data": <ticket doc>} for
tickets with status "pending" (as read from the artifact database).
Output: a JSON object {doc_id: {"legs": [...], "status": ...}} holding
only the tickets whose grading changed — apply each as a document
update. Legs it can grade: moneylines ("KC ML"), alternate spreads
("KC +19.5"), totals ("Over 44.5 pts"). Player props are left for
manual grading on the page. Ties are left pending (a push is the
book's refund case, not a win or a loss).
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import nfl_parlay as np

SPREAD_RE = re.compile(r"^([A-Z]{2,3}) ([+-][\d.]+)$")
TOTAL_RE = re.compile(r"^(Over|Under) ([\d.]+) pts$")


def curl_json(url):
    out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                         capture_output=True, check=True)
    return json.loads(out.stdout)


def finals_for(dates):
    """{'JAX @ DEN': (away_score, home_score)} for final games.

    The plain scoreboard covers the whole current week; per-date
    fetches back-fill older tickets.
    """
    finals = {}
    for d in [None] + sorted(dates):
        try:
            payload = curl_json(np.ESPN_URL + (f"?dates={d}" if d else ""))
        except Exception:
            continue
        for ev in payload.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if comp.get("status", {}).get("type", {}).get("state") != "post":
                continue
            t = {c["homeAway"]: c for c in comp.get("competitors", [])}
            away = t["away"]["team"]["abbreviation"]
            home = t["home"]["team"]["abbreviation"]
            finals[f"{away} @ {home}"] = (int(t["away"].get("score", 0)),
                                          int(t["home"].get("score", 0)))
    return finals


def grade_leg(leg, finals):
    mu = leg.get("matchup", "")
    if mu not in finals or " @ " not in mu:
        return None
    away_s, home_s = finals[mu]
    away, home = mu.split(" @ ")
    kind, desc = leg.get("kind"), leg.get("desc", "")
    if kind == "ml":
        team = desc[:-3].strip()
        if away_s == home_s:
            return None  # tie: a push, leave for the human
        winner = away if away_s > home_s else home
        return "won" if team == winner else "lost"
    if kind == "spread":
        m = SPREAD_RE.match(desc)
        if not m:
            return None
        team, line = m.group(1), float(m.group(2))
        mine = away_s if team == away else home_s if team == home else None
        theirs = home_s if team == away else away_s if team == home else None
        if mine is None:
            return None
        margin = mine + line - theirs
        return None if margin == 0 else ("won" if margin > 0 else "lost")
    if kind == "total":
        m = TOTAL_RE.match(desc)
        if not m:
            return None
        side, line = m.group(1), float(m.group(2))
        total = away_s + home_s
        if total == line:
            return None
        over = total > line
        return "won" if (side == "Over") == over else "lost"
    return None  # props: manual


def main():
    src = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    tickets = json.load(src)
    dates = set()
    for t in tickets:
        placed = t["data"].get("placed", "")[:10]
        if placed:
            d0 = datetime.strptime(placed, "%Y-%m-%d")
            for k in (0, 1, 2):
                dates.add((d0 + timedelta(days=k)).strftime("%Y%m%d"))
    finals = finals_for(dates)
    updates = {}
    for t in tickets:
        doc = t["data"]
        legs = [dict(l) for l in doc.get("legs", [])]
        changed = False
        for leg in legs:
            if leg.get("result") != "pending":
                continue
            verdict = grade_leg(leg, finals)
            if verdict:
                leg["result"] = verdict
                changed = True
        if changed:
            status = ("missed" if any(l["result"] == "lost" for l in legs)
                      else "hit" if all(l["result"] == "won" for l in legs)
                      else "pending")
            updates[t["id"]] = {"legs": legs, "status": status}
    json.dump(updates, sys.stdout, indent=1)
    print(f"\n# {len(updates)} of {len(tickets)} pending tickets updated; "
          f"{len(finals)} finals checked", file=sys.stderr)


if __name__ == "__main__":
    main()
