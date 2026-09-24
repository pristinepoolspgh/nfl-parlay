#!/usr/bin/env python3
"""Game simulator: run the model on each matchup and read the
distribution of outcomes.

Usage:  python3 board/sim.py            # project every upcoming game

Method:
- expected margin comes from the Elo gap (25 rating points ~ one
  point of spread, home field included);
- expected total comes from both teams' scoring profiles (points
  for/against, this season weighted over last), shrunk toward the
  league average while samples are small;
- outcomes are drawn 10,000 times with the NFL's empirical noise
  (margin sd ~13.2, total sd ~10), giving win probability, cover
  probability for any spread, over/under probability for any total,
  and the single most likely final score.

Exact probabilities use the normal CDF (no Monte Carlo noise); the
10,000 draws pick the modal scoreline. The same honesty applies as
everywhere else: the model sees scores only, and its projections
are graded in memory/ against what actually happens.
"""
import json
import math
import os
import random
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

ELO_PATH = os.path.join(BASE, "memory", "elo.json")
MARGIN_SD = 13.2
TOTAL_SD = 10.0
HFA = 48.0
SHRINK_GAMES = 4.0
SIMS = 10000


def _phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


EPA_BLEND_K = 6.0  # games until EPA carries half the margin estimate


class Model:
    # v2: Elo margin blended with nflverse EPA differential.
    # v3: caller-supplied availability dock (starting QB Out/Doubtful)
    #     and weather shift on totals weigh on the prediction.
    # v4: EPA blend CUT after board/backtest.py replayed 2025-26
    #     (224 games): pure-Elo margins beat every blend weight on
    #     Brier (.2245 vs .2247-.2516) and MAE, and ran near the
    #     market itself on logged wk2 favorites (.2438 vs .2416).
    #     Early-season EPA is noise. Docks and weather stay.
    VERSION = 4

    def __init__(self, path=ELO_PATH):
        d = json.load(open(path))
        self.ratings = d["ratings"]
        self.scoring = d.get("scoring", {})
        self.epa = d.get("epa", {})
        self.league_total = d.get("league_total", 44.0)

    def predict(self, home, away, neutral=False,
                dock_home=0.0, dock_away=0.0, total_shift=0.0):
        """Full outcome read for one game. The caller that knows the
        injury report and forecast passes `dock_*` (points off a team
        whose starting QB is Out/Doubtful) and `total_shift` (wind and
        rain pressing the total, usually negative). Zero means the
        prediction stays pure scores-and-efficiency."""
        ra = self.ratings.get(home, 1500.0) + (0.0 if neutral else HFA)
        rb = self.ratings.get(away, 1500.0)
        mu_margin = (ra - rb) / 25.0
        # No EPA blend: backtesting showed it degraded accuracy at
        # every weight tried (see VERSION note). self.epa stays loaded
        # for the reads to cite; it just doesn't move the margin.
        mu_margin += dock_away - dock_home
        sh = self.scoring.get(home, {})
        sa = self.scoring.get(away, {})
        half = self.league_total / 2.0
        raw_total = ((sh.get("pf", half) + sa.get("pa", half)) / 2.0
                     + (sa.get("pf", half) + sh.get("pa", half)) / 2.0)
        n_eff = min(sh.get("n", 0), sa.get("n", 0))
        shrink = n_eff / (n_eff + SHRINK_GAMES)
        mu_total = self.league_total + (raw_total - self.league_total) * shrink
        # A missing starter lowers his own team's scoring too; weather
        # presses both sides. Floor keeps the distribution sane.
        mu_total = max(24.0, mu_total - 0.5 * (dock_home + dock_away)
                       + total_shift)
        # Modal final score from 10,000 draws.
        counts = {}
        for _ in range(SIMS):
            m = random.gauss(mu_margin, MARGIN_SD)
            t = random.gauss(mu_total, TOTAL_SD)
            hs = max(0, round((t + m) / 2.0))
            a_s = max(0, round((t - m) / 2.0))
            counts[(hs, a_s)] = counts.get((hs, a_s), 0) + 1
        modal = max(counts, key=counts.get)
        return {
            "home": home, "away": away,
            "mu_margin": round(mu_margin, 2),
            "mu_total": round(mu_total, 2),
            "p_home": round(1.0 - _phi(-mu_margin / MARGIN_SD), 4),
            "proj": {"home": round((mu_total + mu_margin) / 2.0, 1),
                     "away": round((mu_total - mu_margin) / 2.0, 1)},
            "modal": {"home": modal[0], "away": modal[1]},
        }

    def p_cover(self, mu_margin, team_line_vs_home):
        """P(home margin > -line_for_home). For 'HOME -6.5' pass
        line_vs_home = -6.5; for 'AWAY +3.5' pass +3.5 from the
        home perspective (home -3.5)."""
        return 1.0 - _phi((-team_line_vs_home - mu_margin) / MARGIN_SD)

    def p_over(self, mu_total, line):
        return 1.0 - _phi((line - mu_total) / TOTAL_SD)


def main():
    import nfl_parlay as np
    import subprocess

    def curl_json(url):
        out = subprocess.run(["curl", "-sSg", "--max-time", "25", url],
                             capture_output=True, check=True)
        return json.loads(out.stdout)

    np._get_json = curl_json
    model = Model()
    events, favs = np.fetch_fd_board()
    print(f"{'GAME':<12} {'PROJECTED':<14} {'MOST LIKELY':<12} "
          f"{'WIN%':<14} MARKET")
    for f in favs:
        away, home = f["matchup"].split(" @ ")
        p = model.predict(home, away)
        fav_p = p["p_home"] if f["team"] == home else 1 - p["p_home"]
        print(f"{f['matchup']:<12} "
              f"{home} {p['proj']['home']:.0f}-{p['proj']['away']:.0f} "
              f"{away:<4} "
              f"{p['modal']['home']}-{p['modal']['away']:<8} "
              f"{f['team']} {fav_p*100:5.1f}%      "
              f"{f['p']*100:5.1f}%")


if __name__ == "__main__":
    main()
