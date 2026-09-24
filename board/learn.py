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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settle

MEM = os.path.join(BASE, "memory")
PREGAME = os.path.join(MEM, "pregame.jsonl")
RESULTS = os.path.join(MEM, "results.jsonl")
JUDGMENTS = os.path.join(MEM, "judgments.jsonl")
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

    # Grade any pending judgment leans with the same finals logic the
    # tickets get — my reads face the same ruler as the market.
    judgments = read_jsonl(JUDGMENTS)
    pending_leans = [(j, l) for j in judgments
                     for l in j.get("leans", [])
                     if l.get("result") == "pending"]
    leans_graded = 0
    if pending_leans:
        dates = {j["date"].replace("-", "") for j, _ in pending_leans}
        extra = {(datetime.strptime(d, "%Y%m%d") + timedelta(days=1))
                 .strftime("%Y%m%d") for d in dates}
        jf = fetch_finals(dates | extra)
        for _, lean in pending_leans:
            verdict = settle.grade_leg(lean, jf)
            if verdict:
                lean["result"] = verdict
                leans_graded += 1
        if leans_graded:
            with open(JUDGMENTS, "w") as f:
                for j in judgments:
                    f.write(json.dumps(j) + "\n")

    # Grade the simulator's own predictions against finals.
    SIMLOG = os.path.join(MEM, "simlog.jsonl")
    simlog = read_jsonl(SIMLOG)
    pend = [r for r in simlog if "hs" not in r]
    if pend:
        dates = {r["date"].replace("-", "") for r in pend}
        extra = {(datetime.strptime(d, "%Y%m%d") + timedelta(days=1))
                 .strftime("%Y%m%d") for d in dates}
        sf = fetch_finals(dates | extra)
        changed = False
        for r in pend:
            if r["matchup"] in sf:
                r["as_"], r["hs"] = sf[r["matchup"]]
                changed = True
        if changed:
            with open(SIMLOG, "w") as f:
                for r in simlog:
                    f.write(json.dumps(r) + "\n")
    done_sims = [r for r in simlog if "hs" in r]
    sim_stats = None
    if done_sims:
        decided = [r for r in done_sims if r["hs"] != r["as_"]]
        winner_acc = (sum((r["p_home"] >= 0.5) == (r["hs"] > r["as_"])
                          for r in decided) / len(decided)
                      if decided else None)
        margin_mae = sum(abs((r["hs"] - r["as_"]) - r["mu_margin"])
                         for r in done_sims) / len(done_sims)
        total_mae = sum(abs((r["hs"] + r["as_"]) - r["mu_total"])
                        for r in done_sims) / len(done_sims)
        brier = sum((r["p_home"] - (1.0 if r["hs"] > r["as_"] else
                     0.5 if r["hs"] == r["as_"] else 0.0)) ** 2
                    for r in done_sims) / len(done_sims)
        sim_stats = {"n": len(done_sims),
                     "winner_acc": round(winner_acc, 4) if winner_acc
                     is not None else None,
                     "margin_mae": round(margin_mae, 2),
                     "total_mae": round(total_mae, 2),
                     "brier": round(brier, 4)}
        # Per model version, so an upgrade proves itself on the same
        # scoreboard instead of silently replacing the old record.
        by_v = {}
        for r in done_sims:
            by_v.setdefault(r.get("v", 1), []).append(r)
        if len(by_v) > 1:
            sim_stats["by_version"] = {
                str(v): {"n": len(rs),
                         "margin_mae": round(sum(
                             abs((r["hs"] - r["as_"]) - r["mu_margin"])
                             for r in rs) / len(rs), 2),
                         "brier": round(sum(
                             (r["p_home"] - (1.0 if r["hs"] > r["as_"]
                              else 0.5 if r["hs"] == r["as_"] else 0.0)
                              ) ** 2 for r in rs) / len(rs), 4)}
                for v, rs in sorted(by_v.items())}

    # The crew's ledger: everyone's saved tickets, graded by the same
    # scoreboard. Picks don't feed the score-based sims; they build a
    # record of who hits and whether saved legs beat their quoted odds.
    crew_tickets = read_jsonl(os.path.join(MEM, "tickets.jsonl"))
    crew_picks = read_jsonl(os.path.join(MEM, "picks.jsonl"))
    crew = None
    if crew_tickets:
        people = {}
        for t in crew_tickets:
            o = people.setdefault(t.get("owner") or "",
                                  {"w": 0, "l": 0, "pend": 0,
                                   "net": 0.0, "legs_w": 0, "legs_l": 0})
            if t.get("status") == "hit":
                o["w"] += 1
                o["net"] += (t.get("fdPays") or 0) - (t.get("stake") or 0)
            elif t.get("status") == "missed":
                o["l"] += 1
                o["net"] -= t.get("stake") or 0
            else:
                o["pend"] += 1
        for p in crew_picks:
            o = people.get(p.get("owner") or "")
            if o is None:
                continue
            if p.get("result") == "won":
                o["legs_w"] += 1
            elif p.get("result") == "lost":
                o["legs_l"] += 1
        graded = [p for p in crew_picks
                  if p.get("result") in ("won", "lost")
                  and isinstance(p.get("p"), (int, float))]
        legs = None
        if graded:
            legs = {"n": len(graded),
                    "avg_p": round(sum(p["p"] for p in graded)
                                   / len(graded), 4),
                    "hit": round(sum(p["result"] == "won"
                                     for p in graded) / len(graded), 4)}
        by_kind = {}
        for p in graded:
            k = by_kind.setdefault(p.get("kind") or "?", {"w": 0, "l": 0})
            k["w" if p["result"] == "won" else "l"] += 1
        crew = {"people": [dict(id=oid, **{k: (round(v, 2)
                                if k == "net" else v)
                                for k, v in st.items()})
                           for oid, st in sorted(
                               people.items(),
                               key=lambda kv: -kv[1]["net"])],
                "legs": legs, "by_kind": by_kind}

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
    all_leans = [l for j in judgments for l in j.get("leans", [])]
    lw = sum(1 for l in all_leans if l["result"] == "won")
    ll = sum(1 for l in all_leans if l["result"] == "lost")
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
        "sim": sim_stats,
        "crew": crew,
        "leans": {"won": lw, "lost": ll,
                  "pending": len(all_leans) - lw - ll,
                  "recent": [{"week": j["week"], "desc": l["desc"],
                              "matchup": l["matchup"],
                              "p_market": l["p_market"],
                              "result": l["result"]}
                             for j in judgments[-4:]
                             for l in j.get("leans", [])]},
    }
    json.dump(insights, open(INSIGHTS, "w"), indent=1)
    print(f"{added} games + {leans_graded} leans graded this run; "
          f"{n_all} games in memory; my leans {lw}-{ll}. {summary}")


if __name__ == "__main__":
    main()
