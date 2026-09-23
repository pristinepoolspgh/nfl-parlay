#!/usr/bin/env python3
"""Fold the board's saved tickets into the season memory.

Usage:  python3 board/crew.py tickets_dump.json

The dump is a JSON array of {"id": ..., "data": {...}} rows exported
from the artifact db's `tickets` collection (every viewer's tickets,
owner-tagged). Two ledgers are maintained by merge-on-id, so tickets
deleted from the board later keep their place in history:

- memory/tickets.jsonl — one row per ticket: who, week, stake, payout,
  quoted probability, settled status;
- memory/picks.jsonl — one row per leg: kind, description, the
  de-vigged probability at save time, and how it resolved.

learn.py reads these to put the crew's record and calibration into
insights.json. Owner ids are opaque platform ids; the page resolves
display names at render time and nothing here stores a name.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(BASE, "memory")
TICKETS = os.path.join(MEM, "tickets.jsonl")
PICKS = os.path.join(MEM, "picks.jsonl")


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


def write_jsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: crew.py tickets_dump.json")
    dump = json.load(open(sys.argv[1]))
    os.makedirs(MEM, exist_ok=True)

    tickets = {r["tid"]: r for r in read_jsonl(TICKETS)}
    picks = {(r["tid"], r["i"]): r for r in read_jsonl(PICKS)}
    t_new = t_upd = 0
    for row in dump:
        tid, t = row["id"], row["data"]
        rec = {"tid": tid, "owner": t.get("owner", ""),
               "week": t.get("week"), "placed": t.get("placed"),
               "stake": t.get("stake"), "fdPays": t.get("fdPays"),
               "combined": t.get("combined"), "status": t.get("status")}
        if tid not in tickets:
            t_new += 1
        elif tickets[tid] != rec:
            t_upd += 1
        tickets[tid] = rec
        for i, leg in enumerate(t.get("legs", [])):
            picks[(tid, i)] = {
                "tid": tid, "i": i, "owner": t.get("owner", ""),
                "week": t.get("week"), "kind": leg.get("kind"),
                "desc": leg.get("desc"), "matchup": leg.get("matchup"),
                "p": leg.get("p"), "odds": leg.get("odds"),
                "result": leg.get("result", "pending")}

    write_jsonl(TICKETS, sorted(tickets.values(),
                                key=lambda r: r.get("placed") or ""))
    write_jsonl(PICKS, sorted(picks.values(),
                              key=lambda r: (r["tid"], r["i"])))
    graded = sum(1 for r in picks.values() if r["result"] in ("won", "lost"))
    print(f"crew: {len(tickets)} tickets ({t_new} new, {t_upd} updated), "
          f"{len(picks)} legs, {graded} graded")


if __name__ == "__main__":
    main()
