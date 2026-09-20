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
python3 nfl_parlay.py props DEN              # player prop lines for a game
python3 nfl_parlay.py props DEN --type rush  # just rushing props
python3 nfl_parlay.py slate --demo           # offline sample data
python3 nfl_parlay.py slate --date 20260927  # a specific Sunday (YYYYMMDD)
```

Live mode needs internet access to `site.api.espn.com` and
`sports.core.api.espn.com`; `--demo` runs anywhere on a bundled sample slate.

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

`props <TEAM>` lists the player prop lines for that team's next game —
passing/rushing/receiving yards and receptions by default, `--type
pass|rush|rec|td|all` for more. `parlay --props N` swaps N moneyline legs
for prop legs in the ticket math.

An honesty note: ESPN publishes prop **lines** but not prices. A prop at the
market line is roughly a 50/50 whichever side you take (books charge about
-110 a side), so prop legs are counted at 50% and the side is yours to pick.
Each prop leg roughly halves a ticket's hit probability and doubles its fair
payout. This tool won't invent an edge it doesn't have — if you want props
priced sharper than a coin flip, that takes a real odds feed, not ESPN's.

Estimates, not guarantees. Nothing here is betting advice.
