# nfl-parlay

NFL slate + safest-parlay builder CLI. Pulls the day's NFL games from ESPN's
public scoreboard API, strips the bookmaker's vig out of the moneylines to get
honest win probabilities, and builds the safest N-leg parlay — telling you
plainly whether your target hit-rate is achievable and what a fair ticket pays.

No dependencies, no API key. Python 3.6+.

## Usage

```
python3 nfl_parlay.py slate                  # today's games + win probs
python3 nfl_parlay.py parlay                 # best 4-leg parlay
python3 nfl_parlay.py parlay --legs 3        # best 3-leg parlay
python3 nfl_parlay.py parlay --target 0.90   # aim for 90% combined
python3 nfl_parlay.py parlay --stake 25      # payout math on $25
python3 nfl_parlay.py slate --demo           # offline sample data
python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)
```

Live mode needs internet access to `site.api.espn.com`; `--demo` runs anywhere
on a bundled sample slate.

## What the numbers mean

- **WIN %** — the market's implied win probability after removing the vig, so
  each game's two sides sum to 100%.
- **FAIR ML** — the American moneyline that probability is worth with no
  bookmaker margin. Books will always pay less than this.
- **COMBINED HIT PROBABILITY** — the product of the legs' probabilities,
  assuming independence.
- The target check tells you when a hit-rate goal (say 90%) simply isn't
  reachable on straight moneylines, and roughly what a true 90% ticket pays.

Estimates, not guarantees. Nothing here is betting advice.
