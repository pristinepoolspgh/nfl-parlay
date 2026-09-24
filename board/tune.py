#!/usr/bin/env python3
"""Tune the margin model on 12 seasons against the closing line.

Usage:  python3 board/tune.py

Experiments, each judged on Brier vs the de-vigged closing moneyline
over the same 2015-2026 scored set as board/backtest.py, with paired
95% CIs against the running baseline (greedy: adopt a step only when
its CI excludes zero, then tune the next knob on top):

  1. MARGIN_SD  — the probability curve's width (pure calibration).
  2. Elo K / HFA — update speed and home-field, full replays.
  3. Rest — margin += c * (home_rest - away_rest), from games.csv.
  4. QB change — dock a team whose listed starter differs from its
     most-used QB of the season so far (min 3 prior starts): the
     historical test of the live model's 4-point dock.

Greedy tuning on one 12-season sample can overfit; anything adopted
here should stay adopted only while the live per-version grading
agrees with it.
"""
import csv
import io
import math
import subprocess
from collections import Counter

GAMES_URL = ("https://raw.githubusercontent.com/nflverse/nfldata/"
             "master/data/games.csv")
ALIAS = {"SD": "LAC", "OAK": "LV", "STL": "LAR", "LA": "LAR",
         "WAS": "WSH", "JAC": "JAX", "ARZ": "ARI"}
SCORE_FROM, WARM_FROM, WEEK_FROM = 2015, 2006, 5


def curl(url):
    out = subprocess.run(["curl", "-sSgL", "--max-time", "60", url],
                         capture_output=True, check=True)
    return out.stdout.decode()


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def devig(hml, aml):
    def imp(o):
        o = float(o)
        return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)
    a, b = imp(hml), imp(aml)
    return a / (a + b)


def load_games():
    rows = list(csv.DictReader(io.StringIO(curl(GAMES_URL))))
    games = []
    for r in rows:
        try:
            season, week = int(r["season"]), int(r["week"])
            hs, as_ = int(r["home_score"]), int(r["away_score"])
        except (ValueError, KeyError):
            continue
        if season < WARM_FROM or season > 2026:
            continue
        games.append({
            "season": season, "week": week, "reg": r["game_type"] == "REG",
            "home": ALIAS.get(r["home_team"], r["home_team"]),
            "away": ALIAS.get(r["away_team"], r["away_team"]),
            "hs": hs, "as": as_, "neutral": r.get("location") == "Neutral",
            "hrest": int(r["home_rest"]) if r.get("home_rest") else 7,
            "arest": int(r["away_rest"]) if r.get("away_rest") else 7,
            "hqb": r.get("home_qb_name") or "", "aqb": r.get("away_qb_name") or "",
            "hml": r.get("home_moneyline") or None,
            "aml": r.get("away_moneyline") or None})
    games.sort(key=lambda g: (g["season"], 0 if g["reg"] else 1, g["week"]))
    return games


def replay(games, K, HFA, regress=1 / 3):
    """Elo margins for scored games at these constants. Also carries
    per-game context (rest, QB-change flags) computed pregame."""
    ratings = {}
    cur = None
    qb_starts = {}  # (season, team) -> Counter of QB names, prior games
    rows = []

    def exp_home(ra, rb):
        return 1.0 / (1.0 + 10 ** (-(ra - rb) / 400.0))

    for g in games:
        if g["season"] != cur:
            if cur is not None:
                for t in ratings:
                    ratings[t] = 1500.0 + (ratings[t] - 1500.0) * (1 - regress)
            cur = g["season"]
        if (g["reg"] and g["season"] >= SCORE_FROM
                and g["week"] >= WEEK_FROM and g["hs"] != g["as"]
                and g["hml"] and g["aml"]):
            ra = ratings.get(g["home"], 1500.0) + (0 if g["neutral"] else HFA)
            rb = ratings.get(g["away"], 1500.0)
            newqb_h = newqb_a = False
            for side, team, qb in (("h", g["home"], g["hqb"]),
                                   ("a", g["away"], g["aqb"])):
                c = qb_starts.get((g["season"], team))
                if qb and c and sum(c.values()) >= 3:
                    usual, _ = c.most_common(1)[0]
                    if qb != usual:
                        if side == "h":
                            newqb_h = True
                        else:
                            newqb_a = True
            rows.append({"m": (ra - rb) / 25.0,
                         "actual": g["hs"] - g["as"],
                         "pm": devig(g["hml"], g["aml"]),
                         "dr": g["hrest"] - g["arest"],
                         "nh": newqb_h, "na": newqb_a})
        # update
        ra = ratings.setdefault(g["home"], 1500.0)
        rb = ratings.setdefault(g["away"], 1500.0)
        hfa = 0.0 if g["neutral"] else HFA
        eh = exp_home(ra + hfa, rb)
        actual = 0.5 if g["hs"] == g["as"] else (1.0 if g["hs"] > g["as"] else 0.0)
        margin = abs(g["hs"] - g["as"]) or 1
        wdiff = (ra + hfa - rb) if g["hs"] >= g["as"] else (rb - ra - hfa)
        mov = math.log(margin + 1) * (2.2 / (wdiff * 0.001 + 2.2))
        delta = K * mov * (actual - eh)
        ratings[g["home"]] = ra + delta
        ratings[g["away"]] = rb - delta
        if g["reg"]:
            for team, qb in ((g["home"], g["hqb"]), (g["away"], g["aqb"])):
                if qb:
                    qb_starts.setdefault((g["season"], team),
                                         Counter())[qb] += 1
    return rows


def brier(rows, sd, rest_c=0.0, qb_dock=0.0):
    bs = []
    for r in rows:
        m = r["m"] + rest_c * r["dr"]
        if r["nh"]:
            m -= qb_dock
        if r["na"]:
            m += qb_dock
        p = _phi(m / sd)
        bs.append((p - (1.0 if r["actual"] > 0 else 0.0)) ** 2)
    return bs


def ci_vs(bs, base):
    n = len(bs)
    diffs = [b - a for b, a in zip(bs, base)]
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    return mean, 1.96 * math.sqrt(var / n)


def main():
    games = load_games()
    base_rows = replay(games, 20.0, 48.0)
    n = len(base_rows)
    mkt = sum((r["pm"] - (1.0 if r["actual"] > 0 else 0.0)) ** 2
              for r in base_rows) / n
    print(f"{n} scored games; closing-line Brier {mkt:.4f}")

    print("\n1) MARGIN_SD (baseline Elo K=20 HFA=48)")
    base = brier(base_rows, 13.2)
    best_sd, best = 13.2, sum(base) / n
    for sd in (12.0, 12.6, 13.2, 13.8, 14.4, 15.0):
        bs = brier(base_rows, sd)
        m, ci = ci_vs(bs, base)
        b = sum(bs) / n
        print(f"  SD={sd:<5} Brier {b:.4f}  Δ {m:+.4f} ±{ci:.4f}")
        if b < best and abs(m) > ci:
            best, best_sd = b, sd
    print(f"  -> adopt SD={best_sd}")

    print("\n2) Elo K / HFA (at adopted SD)")
    base2 = brier(base_rows, best_sd)
    best_kh, bestb = (20.0, 48.0), sum(base2) / n
    for K in (15.0, 20.0, 25.0):
        for HFA in (30.0, 48.0, 65.0):
            rows = base_rows if (K, HFA) == (20.0, 48.0) \
                else replay(games, K, HFA)
            bs = brier(rows, best_sd)
            m, ci = ci_vs(bs, base2)
            b = sum(bs) / n
            flag = " *" if b < bestb and abs(m) > ci else ""
            print(f"  K={K:<4} HFA={HFA:<4} Brier {b:.4f}  Δ {m:+.4f} ±{ci:.4f}{flag}")
            if b < bestb and abs(m) > ci:
                bestb, best_kh = b, (K, HFA)
    print(f"  -> adopt K={best_kh[0]} HFA={best_kh[1]}")
    rows = base_rows if best_kh == (20.0, 48.0) else replay(games, *best_kh)

    print("\n3) Rest coefficient (pts per rest-day differential)")
    base3 = brier(rows, best_sd)
    best_c, bestb = 0.0, sum(base3) / n
    for c in (0.0, 0.05, 0.1, 0.15, 0.2):
        bs = brier(rows, best_sd, rest_c=c)
        m, ci = ci_vs(bs, base3)
        b = sum(bs) / n
        print(f"  c={c:<5} Brier {b:.4f}  Δ {m:+.4f} ±{ci:.4f}")
        if b < bestb and abs(m) > ci:
            bestb, best_c = b, c
    print(f"  -> adopt rest c={best_c}")

    print("\n4) QB-change dock (starter differs from season's usual)")
    nq = sum(1 for r in rows if r["nh"] or r["na"])
    print(f"  games with a changed starter: {nq}")
    base4 = brier(rows, best_sd, rest_c=best_c)
    best_d, bestb = 0.0, sum(base4) / n
    for d in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0):
        bs = brier(rows, best_sd, rest_c=best_c, qb_dock=d)
        m, ci = ci_vs(bs, base4)
        b = sum(bs) / n
        print(f"  dock={d:<4} Brier {b:.4f}  Δ {m:+.4f} ±{ci:.4f}")
        if b < bestb and abs(m) > ci:
            bestb, best_d = b, d
    print(f"  -> adopt qb dock={best_d}")
    print(f"\nfinal Brier {bestb:.4f} vs market {mkt:.4f} "
          f"(gap {bestb - mkt:+.4f})")


if __name__ == "__main__":
    main()
