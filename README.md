# nfl-parlay

NFL slate + safest-parlay builder CLI. Pulls the day's NFL games from ESPN's
public scoreboard API, strips the bookmaker's vig out of the moneylines to get
honest win probabilities, and builds the safest N-leg parlay — telling you
plainly whether your target hit-rate is achievable and what a fair ticket pays.

No dependencies, no API key. Python 3.6+ (3.9+ for Eastern-time kickoffs).

## Usage

```
python3 nfl_parlay.py slate                  # today's games + win probs
python3 nfl_parlay.py parlay                 # best 4-leg parlay
python3 nfl_parlay.py parlay --legs 3        # best 3-leg parlay
python3 nfl_parlay.py parlay --target 0.90   # aim for 90% combined
python3 nfl_parlay.py parlay --stake 25      # payout math on $25
python3 nfl_parlay.py parlay --props 2       # swap 2 legs for player props
python3 nfl_parlay.py props DEN              # player props with prices
python3 nfl_parlay.py props DEN --alts       # include alternate lines
python3 nfl_parlay.py props DEN --type rush  # just rushing props
python3 nfl_parlay.py slate --demo           # offline sample data
python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)
```

Live mode needs internet access to `site.api.espn.com` (game lines) and
`www.bovada.lv` (prop prices); `--demo` runs anywhere on bundled sample data.

## What the numbers mean

- **WIN %** — the market's implied win probability after removing the vig, so
  each game's two sides sum to 100%.
- **FAIR ML** — the American moneyline that probability is worth with no
  bookmaker margin. Books will always pay less than this.
- **COMBINED HIT PROBABILITY** — the product of the legs' probabilities,
  assuming independence.
- The target check tells you when a hit-rate goal (say 90%) simply isn't
  reachable on straight moneylines, and roughly what a true 90% ticket pays.

## Player props

`props <TEAM>` lists player props for that team's next game with real
prices from Bovada's public JSON — both sides of every line, de-vigged into
probabilities that sum to 100%. Defaults to the core full-game
yardage/receptions markets at the main line; `--alts` shows every alternate
line, `--type pass|rush|rec|td|all` filters, `--limit` caps the count.

`parlay --props N` swaps N moneyline legs for the safest priced prop sides
on the whole board (alternate lines included, at most one leg per player).
Two honest caveats: the math treats legs as independent, but books price
same-game combos (SGPs) differently and may bar some combinations; and if
Bovada is unreachable the tool falls back to ESPN, which publishes only
lines — a prop at the market line is ~50/50 either side, and the output
says so rather than inventing an edge.

Bovada's endpoints are public but unofficial, so they can change without
notice; `--source espn` forces the fallback if they do.

Estimates, not guarantees. Nothing here is betting advice.
