#!/usr/bin/env python3
"""Backtest the margin model against the closing line, 2015-2026.

Usage:  python3 board/backtest.py

Data: nflverse games.csv (results + CLOSING spread and moneylines,
franchises unified across relocations) and nflverse weekly team EPA
per season. Elo replays 2006 onward (warm-up years unscored);
predictions score 2015+ regular season, week 5 onward, using only
information from before each kickoff.

Models: pure Elo; Elo/EPA blends (w = n/(n+K)) with RAW EPA and with
OPPONENT-ADJUSTED EPA (iterative: each offense judged against the
quality of defenses faced, and vice versa); pure adjusted EPA.
Benchmark: the closing line itself — de-vigged moneyline for Brier,
spread for margin MAE. Note the market benchmark carries information
the models can't have (injuries, QB changes, weather), so matching it
is strong and beating it would be extraordinary.

Decision rule, fixed in advance: a blend replaces pure Elo only if
its paired Brier improvement has a 95% CI excluding zero. Winner% is
reported but decides nothing — it ignores calibration.
"""
import csv
import io
import math
import os
import subprocess
import sys

GAMES_URL = ("https://raw.githubusercontent.com/nflverse/nfldata/"
             "master/data/games.csv")
EPA_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
           "stats_team/stats_team_week_{season}.csv")
ALIAS = {"SD": "LAC", "OAK": "LV", "STL": "LAR", "LA": "LAR",
         "WAS": "WSH", "JAC": "JAX", "ARZ": "ARI"}
K_ELO, HFA, REGRESS = 20.0, 48.0, 1 / 3
MARGIN_SD = 13.2
SCORE_FROM, WARM_FROM, WEEK_FROM = 2015, 2006, 5
GRID = [("pure Elo", None, False), ("raw K=12", 12.0, False),
        ("raw K=6", 6.0, False), ("raw K=3", 3.0, False),
        ("adj K=12", 12.0, True), ("adj K=6", 6.0, True),
        ("adj K=3", 3.0, True), ("pure adjEPA", 0.0, True)]


def curl(url):
    out = subprocess.run(["curl", "-sSgL", "--max-time", "60", url],
                         capture_output=True, check=True)
    return out.stdout.decode()


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def devig(home_ml, away_ml):
    def imp(o):
        o = float(o)
        return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)
    a, b = imp(home_ml), imp(away_ml)
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
            "hs": hs, "as": as_,
            "neutral": r.get("location") == "Neutral",
            "spread": float(r["spread_line"]) if r.get("spread_line") else None,
            "hml": r.get("home_moneyline") or None,
            "aml": r.get("away_moneyline") or None})
    games.sort(key=lambda g: (g["season"], 0 if g["reg"] else 1, g["week"]))
    return games


def elo_expected(ra, rb):
    return 1.0 / (1.0 + 10 ** (-(ra - rb) / 400.0))


def elo_update(ratings, g):
    ra = ratings.setdefault(g["home"], 1500.0)
    rb = ratings.setdefault(g["away"], 1500.0)
    hfa = 0.0 if g["neutral"] else HFA
    exp_home = elo_expected(ra + hfa, rb)
    actual = 0.5 if g["hs"] == g["as"] else (1.0 if g["hs"] > g["as"] else 0.0)
    margin = abs(g["hs"] - g["as"]) or 1
    wdiff = (ra + hfa - rb) if g["hs"] >= g["as"] else (rb - ra - hfa)
    mov = math.log(margin + 1) * (2.2 / (wdiff * 0.001 + 2.2))
    delta = K_ELO * mov * (actual - exp_home)
    ratings[g["home"]] = ra + delta
    ratings[g["away"]] = rb - delta


def season_epa(season):
    """[(team, week, opp, epa)] regular-season rows, or []."""
    try:
        rows = list(csv.DictReader(io.StringIO(
            curl(EPA_URL.format(season=season)))))
    except Exception:
        return []
    out = []
    for r in rows:
        if r.get("season_type") != "REG":
            continue
        try:
            e = (float(r.get("passing_epa") or 0)
                 + float(r.get("rushing_epa") or 0))
            w = int(r["week"])
        except (ValueError, KeyError):
            continue
        out.append((ALIAS.get(r["team"], r["team"]), w,
                    ALIAS.get(r.get("opponent_team", ""),
                              r.get("opponent_team", "")), e))
    return out


def snapshots(rows, adjust):
    """{week: {team: (off_rel, def_rel, n)}} using weeks < week.
    Values are relative to league average; margin uses
    (offH - offA) + (defA - defH). Adjusted mode iterates so each
    offense is judged against the defenses it faced."""
    weeks = sorted({w for _, w, _, _ in rows})
    snaps = {}
    for upto in weeks[1:] + [max(weeks) + 1]:
        sub = [(t, w, o, e) for t, w, o, e in rows if w < upto]
        if not sub:
            continue
        league = sum(e for *_, e in sub) / len(sub)
        by_team, faced = {}, {}
        for t, w, o, e in sub:
            by_team.setdefault(t, []).append((o, e))
        allowed = {}
        for t, gs in by_team.items():
            for o, e in gs:
                allowed.setdefault(o, []).append((t, e))
        off = {t: sum(e for _, e in gs) / len(gs) - league
               for t, gs in by_team.items()}
        dfn = {t: sum(e for _, e in gs) / len(gs) - league
               for t, gs in allowed.items()}
        if adjust:
            for _ in range(6):
                off = {t: sum(e - league - dfn.get(o, 0.0)
                              for o, e in gs) / len(gs)
                       for t, gs in by_team.items()}
                dfn = {t: sum(e - league - off.get(o, 0.0)
                              for o, e in gs) / len(gs)
                       for t, gs in allowed.items()}
        snaps[upto] = {t: (off.get(t, 0.0), dfn.get(t, 0.0),
                           len(by_team.get(t, [])))
                       for t in by_team}
    return snaps


def main():
    games = load_games()
    print(f"{len(games)} games loaded 2006-2026; scoring "
          f"{SCORE_FROM}+ REG week {WEEK_FROM}+ with closing lines")
    ratings = {}
    cur_season = None
    epa_raw = epa_adj = None
    rows = []  # per scored game: dict of model margins + market + actual

    for g in games:
        if g["season"] != cur_season:
            if cur_season is not None:
                for t in ratings:
                    ratings[t] = 1500.0 + (ratings[t] - 1500.0) * (1 - REGRESS)
            cur_season = g["season"]
            epa_raw = epa_adj = None
            if cur_season >= SCORE_FROM:
                er = season_epa(cur_season)
                epa_raw = snapshots(er, adjust=False)
                epa_adj = snapshots(er, adjust=True)
        if (g["reg"] and g["season"] >= SCORE_FROM
                and g["week"] >= WEEK_FROM and g["hs"] != g["as"]
                and g["spread"] is not None and g["hml"] and g["aml"]):
            ra = ratings.get(g["home"], 1500.0) + (0 if g["neutral"] else HFA)
            rb = ratings.get(g["away"], 1500.0)
            m_elo = (ra - rb) / 25.0
            hfa_pts = 0.0 if g["neutral"] else HFA / 25.0
            row = {"actual": g["hs"] - g["as"], "spread": g["spread"],
                   "pm": devig(g["hml"], g["aml"]), "m": {}}
            for name, k, adj in GRID:
                if k is None:
                    row["m"][name] = m_elo
                    continue
                snaps = epa_adj if adj else epa_raw
                snap = snaps.get(g["week"], {}) if snaps else {}
                eh, ea = snap.get(g["home"]), snap.get(g["away"])
                if not eh or not ea:
                    row["m"][name] = m_elo
                    continue
                m_epa = (eh[0] - ea[0]) + (ea[1] - eh[1]) + hfa_pts
                if k == 0:
                    row["m"][name] = m_epa
                else:
                    n = min(eh[2], ea[2])
                    w = n / (n + k)
                    row["m"][name] = (1 - w) * m_elo + w * m_epa
            rows.append(row)
        elo_update(ratings, g)

    n = len(rows)
    seasons = SCORE_FROM
    print(f"\nScored: {n} games ({2026 - SCORE_FROM + 1} seasons)")
    mkt_brier = sum((r["pm"] - (1.0 if r["actual"] > 0 else 0.0)) ** 2
                    for r in rows) / n
    mkt_mae = sum(abs(r["spread"] - r["actual"]) for r in rows) / n
    mkt_acc = sum((r["spread"] > 0) == (r["actual"] > 0)
                  for r in rows if r["spread"] != 0) / \
        sum(1 for r in rows if r["spread"] != 0)
    print(f"\n{'model':<13}{'winner%':>8}{'MAE':>7}{'Brier':>8}"
          f"{'ΔBrier vs Elo (95% CI)':>26}{'Δ vs market':>12}")
    print(f"{'CLOSING LINE':<13}{mkt_acc*100:>7.1f}%{mkt_mae:>7.2f}"
          f"{mkt_brier:>8.4f}{'—':>26}{'—':>12}")
    base = [( _phi(r['m']['pure Elo'] / MARGIN_SD)
              - (1.0 if r["actual"] > 0 else 0.0)) ** 2 for r in rows]
    for name, k, adj in GRID:
        bs = [(_phi(r["m"][name] / MARGIN_SD)
               - (1.0 if r["actual"] > 0 else 0.0)) ** 2 for r in rows]
        acc = sum((r["m"][name] > 0) == (r["actual"] > 0)
                  for r in rows) / n
        mae = sum(abs(r["m"][name] - r["actual"]) for r in rows) / n
        brier = sum(bs) / n
        diffs = [b - a for b, a in zip(bs, base)]
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        ci = 1.96 * math.sqrt(var / n)
        dm = brier - mkt_brier
        print(f"{name:<13}{acc*100:>7.1f}%{mae:>7.2f}{brier:>8.4f}"
              f"{mean:>+13.4f} ±{ci:.4f}{dm:>+12.4f}")


if __name__ == "__main__":
    main()
