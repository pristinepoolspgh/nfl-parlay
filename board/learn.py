#!/usr/bin/env python3
"""Grow the Parlay Board's season memory.

Usage:  python3 board/learn.py

Joins memory/pregame.jsonl (favorite lines logged at snapshot time)
against ESPN finals, appends newly decided games to
memory/results.jsonl, and rebuilds memory/insights.json:

- calibration: per probability bucket, what the market said vs what
  actually happened (the honest test of "safest");
- upsets: favorites that lost, strongest first;
- a one-line read the board can show.

Prints what changed. Exit code 0 always; grading what it can and
leaving the rest for a later run is the normal case.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import nfl_parlay as np

MEM = os.path.join(BASE, "memory")
PREGAME = os.path.join(MEM, "pregame.jsonl")
RESULTS = os.path.join(MEM, "results.jsonl")
INSIGHTS = os.path.join(MEM, "insights.json")

BUCKETS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def curl_json(url):
    out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                         capture_output=True, check=True)
    return json.loads(out.stdout)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def fetch_finals(dates):
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


def main():
    pregame = read_jsonl(PREGAME)
    results = read_jsonl(RESULTS)
    done = {(r["date"], r["matchup"]) for r in results}
    open_lines = [r for r in pregame
                  if (r["date"], r["matchup"]) not in done]
    if open_lines:
        dates = {r["date"].replace("-", "") for r in open_lines}
        extra = {(datetime.strptime(d, "%Y%m%d") + timedelta(days=1))
                 .strftime("%Y%m%d") for d in dates}
        finals = fetch_finals(dates | extra)
        os.makedirs(MEM, exist_ok=True)
        added = 0
        with open(RESULTS, "a") as f:
            for r in open_lines:
                mu = r["matchup"]
                if mu not in finals or " @ " not in mu:
                    continue
                away_s, home_s = finals[mu]
                if away_s == home_s:
                    continue  # tie: no lesson about the favorite
                away, home = mu.split(" @ ")
                winner = away if away_s > home_s else home
                rec = dict(r)
                rec["fav_won"] = (r["fav"] == winner)
                rec["upset"] = not rec["fav_won"]
                rec["score"] = f"{away} {away_s} - {home} {home_s}"
                f.write(json.dumps(rec) + "\n")
                results.append(rec)
                added += 1
    else:
        added = 0

    # Rebuild insights from the full results file.
    buckets = []
    for lo, hi in BUCKETS:
        rows = [r for r in results if lo <= r["p_fav"] < hi]
        n = len(rows)
        buckets.append({
            "range": f"{int(lo*100)}-{int(min(hi,1)*100)}%",
            "n": n,
            "predicted": round(sum(r["p_fav"] for r in rows) / n, 4) if n else None,
            "actual": round(sum(r["fav_won"] for r in rows) / n, 4) if n else None,
        })
    upsets = sorted([r for r in results if r["upset"]],
                    key=lambda r: -r["p_fav"])
    n_all = len(results)
    pred_all = sum(r["p_fav"] for r in results) / n_all if n_all else 0
    act_all = sum(r["fav_won"] for r in results) / n_all if n_all else 0
    summary = (f"{n_all} favorites graded: market said "
               f"{pred_all*100:.1f}%, they actually won "
               f"{act_all*100:.1f}%."
               if n_all else "No graded games yet.")
    insights = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"),
        "games": n_all,
        "predicted": round(pred_all, 4),
        "actual": round(act_all, 4),
        "summary": summary,
        "buckets": buckets,
        "upsets": [{"week": r["week"], "matchup": r["matchup"],
                    "fav": r["fav"], "p_fav": r["p_fav"],
                    "score": r["score"]} for r in upsets[:12]],
    }
    json.dump(insights, open(INSIGHTS, "w"), indent=1)
    print(f"{added} games graded this run; {n_all} in memory. {summary}")


if __name__ == "__main__":
    main()
