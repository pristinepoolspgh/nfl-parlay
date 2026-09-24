# Research Playbook

> **Repo notes (added by the agent, Sep 2026).** This document was supplied
> by the owner as the standing research reference for the Parlay Board.
> How it maps to this repo today:
> - **Already wired:** availability (ESPN injuries API → board "inj"),
>   news (ESPN + NFL.com merged → board "news"), weather at kickoff hour
>   (Open-Meteo → "wx", roof status per stadium), market-as-data (de-vigged
>   FanDuel board; first-seen lines in memory/pregame.jsonl vs latest
>   sightings in memory/close.jsonl is our open-vs-close movement signal),
>   player records on demand (board/player.py, ESPN athlete APIs), CLV raw
>   material (close.jsonl), result ledgers (memory/), Elo + score sims
>   (board/elo.py, board/sim.py).
> - **Also wired (Sep 24):** nflverse team stats — direct release-asset
>   downloads pass the proxy even though GitHub's HTML pages don't —
>   via board/epa.py (offensive EPA/game + CPOE per team); Rotowire's
>   NFL news feed as a third news source in the board's "news" field,
>   which relays beat-writer/insider reporting (often X-sourced, with
>   attribution) minutes after it breaks — the practical substitute for
>   direct X access.
> - **Reachable from this sandbox, not yet wired:** nflpenalties.com
>   (crew flag rates), rbsdm.com (page loads; its data is a JS app;
>   the same numbers come from nflverse), nflverse play-by-play (large;
>   would enable defensive EPA).
> - **Not reachable / not usable here:** NFL Next Gen Stats API (401
>   without keys), all paid tools (OddsJam, PropFinder, Outlier, PFF,
>   etc.), X/Twitter directly (login wall; API read access is a paid
>   tier). Treat any claim that depends on them as unverifiable here.
> - The weekly cadence in Part 5.6 is approximated by the Routines:
>   Tue morning (grade + roll the week), Thu/Mon night (pregame read),
>   Sun 11 AM–7 PM ET every 2 hours (reads, refreshes, settlement), plus
>   a noon-ET Sunday firing to re-check inactives (~11:30 AM ET post).

---

# README: What Moves Final Scores, and Where to Pull the Data

**Purpose:** Reference guide for an agent building parlay and player-prop cards. Part 1 explains the factors that actually change a game's final score (and therefore player stat lines). Part 2 maps each data source to the factors it covers, what to pull, and its limitations. Part 3 is the recommended research workflow. Part 4 is a list of rules that prevent the most common mistakes.

Sports covered: NFL, NBA, MLB, NHL, with notes on college football/basketball where relevant.

---

## Part 1: The Factors That Change Final Scores

A final score is the product of three things: **how many possessions/plate appearances/shifts happen** (volume), **how efficiently each side converts them** (efficiency), and **randomness** (variance). Almost every useful input maps to one of those three. A player prop is the same equation applied to one player: his share of the volume, times his efficiency, plus variance.

### 1.1 Availability (highest priority, most time-sensitive)

- **Injuries and inactives.** The single largest driver of line movement. A starting QB, a starting pitcher, or an NBA star being out can move a spread 3–7 points and reshuffle every prop on the board. An injury to a *secondary* player (WR2, a starting center, a bullpen closer) often moves the market less than it should, which is where props get mispriced.
- **Rest and load management (NBA especially).** Back-to-backs, 3-in-4s, long road trips. Stars sit or play reduced minutes. Check the injury report *and* the schedule.
- **Roster changes.** Trades, call-ups, waiver claims, suspensions, returns from IL/IR.
- **Redistribution effect.** When a player is out, his volume goes somewhere. The agent should ask: who absorbs the targets, shots, or at-bats? That is usually the best prop opportunity, not the obvious "star is out, fade the team" angle.

### 1.2 Volume / Pace / Game Environment

- **Pace (NBA):** possessions per 48 minutes. Two fast teams produce more points, rebounds, assists, and turnovers for everyone. Two slow teams suppress all counting stats.
- **Plays per game and time of possession (NFL):** teams that pass a lot and play up-tempo generate more plays; run-heavy teams bleed the clock and cap opponent volume too.
- **Total (over/under) as a proxy:** the market total is a compressed estimate of expected volume and efficiency. A prop line that hasn't adjusted after a total moved is a signal.
- **Game script:** expected margin changes how a game is played. A team expected to trail throws more (pass volume up, rush volume down); a team expected to lead runs the clock. In the NBA, blowouts produce garbage-time minutes for bench players and cap starters' minutes.
- **Usage / target share / touches:** the player's slice of the team's volume. Usage rate (NBA), target share and air yards (NFL), lineup slot and plate appearances (MLB), power-play time and TOI (NHL).

### 1.3 Matchup / Efficiency

- **Defense vs. position (DvP):** how a defense performs against a specific position or archetype. Useful but noisy early in a season; weight it more after 8–10 games.
- **Scheme matchups:** zone-heavy NFL defenses concede short completions (good for receptions props, bad for yards-per-catch); man-heavy defenses create big-play variance. Blitz rate vs. a QB's pressure-handling.
- **Batter vs. pitcher handedness splits (MLB):** platoon splits are among the most reliable single-game edges. Also check pitch mix vs. the batter's known weaknesses (e.g., high-velocity fastballs, breaking balls).
- **Pitcher quality and bullpen quality (MLB):** starting pitcher expected innings, and whether the bullpen is fresh or gassed (check usage over the last 3 days). Bullpen fatigue is systematically under-priced in totals.
- **Goalie (NHL):** confirmed starter vs. backup is the NHL equivalent of the starting QB. Save percentage on recent form and rest days.
- **Home/away and travel:** home-field edges have shrunk but still exist. Cross-country travel, altitude (Denver), and time-zone changes (West Coast teams playing 1 p.m. ET) are measurable.

### 1.4 Environment (mostly outdoor sports)

- **Wind (NFL, MLB):** the most important weather variable. Sustained wind over ~15 mph reduces passing yards, field-goal range, and home runs. Wind direction at a specific stadium matters (Wrigley, Oracle Park, Soldier Field).
- **Rain / snow / cold:** modestly reduces passing efficiency and totals; increases fumbles. Extreme cold affects ball flight and kicking.
- **Ballpark factors (MLB):** Coors Field, Great American Ball Park, and Yankee Stadium inflate runs and HRs; Oracle Park, T-Mobile, and Petco suppress them. Park factor should be applied to every MLB total and hitting prop.
- **Domes / roofs:** neutralize weather entirely. Confirm roof status for retractable stadiums.

### 1.5 Officiating

- **NBA referee crews:** measurable differences in foul rate, free throws, and pace. Certain crews correlate with higher totals.
- **MLB umpires:** strike-zone size affects walks, strikeouts, and runs. Umpire assignments are usually posted the morning of the game.
- **NFL crews:** penalty rates vary, which affects drive length and pace.

### 1.6 Motivation and Situational Spots

- Playoff seeding, elimination, tanking (NBA late season), lookahead/letdown spots (a team playing before or after a marquee game), revenge games (mostly noise), rivalry games (slightly more variance).
- End-of-season resting: teams locked into seeding rest starters; teams out of contention give minutes to young players.

### 1.7 Market Information (the line itself is data)

- **Opening line vs. current line:** the direction of movement tells you what new information the market absorbed.
- **Sharp vs. public money:** when the majority of bets are on one side but the line moves the other way, sharp money is on the other side ("reverse line movement").
- **Book discrepancies:** the same prop priced differently across books. The book with the "off" number is usually wrong, not right.
- **Sharp-book benchmark:** Pinnacle and Circa lines are the most efficient reference points. Compare a US book's prop to the sharp consensus.

### 1.8 Variance (what cannot be predicted)

Turnover luck, injuries during the game, shooting variance, bullpen blowups, and referee decisions. The agent should never claim a leg is "a lock." The goal is to find legs where the true probability is higher than the implied probability from the odds, then let the sample size work. Parlays multiply the book's margin on every leg, so the edge on each leg must be real.

### 1.9 Factor Weighting by Sport (rough guidance)

| Factor | NFL | NBA | MLB | NHL |
|---|---|---|---|---|
| Injuries / availability | Very high | Very high | High (SP, lineup) | Very high (goalie) |
| Pace / volume | High | Very high | Medium | Medium |
| Matchup (DvP, splits) | Medium–High | Medium | Very high (handedness, park) | Medium |
| Weather | High (wind) | None | High (wind, temp) | None |
| Rest / schedule | Medium | Very high | Low–Medium | High (B2B goalie) |
| Officials | Low–Medium | Medium | Medium (umps) | Low |
| Bullpen / depth fatigue | Low | Medium (bench) | Very high | Medium |
| Line movement / sharp money | High | High | High | High |

---

## Part 2: Data Sources, What They Cover, and How to Use Them

### 2.1 Odds Comparison, Line Movement, and Market Signals

**OddsJam** (oddsjam.com) — Paid.
- Covers: real-time odds across every major US book, positive-EV finder, arbitrage finder, line history, prop odds screens.
- Pull: best available price for a given prop, implied probability, "fair" odds from the devigged consensus, and line movement since open.
- Use for: Factor 1.7. Confirming whether a prop's price at a specific book is out of line with the market.
- Caveats: the +EV tool is only as good as the sharp books it uses as reference. Don't treat "+EV" as an automatic bet; it's a filter.

**OddsShopper** (oddsshopper.com) — Free tier plus paid.
- Similar to OddsJam with a stronger prop-focused UI and DFS (PrizePicks/Underdog) pricing comparisons.
- Use for: finding the best number when the same prop is offered on several books.

**Action Network** (actionnetwork.com) — Free tier plus paid.
- Covers: line movement charts, opening vs. current lines, public bet percentage vs. money percentage, injury news, expert picks.
- Pull: bet% vs. money% splits (reverse line movement), line history, and PRO projections if subscribed.
- Use for: Factor 1.7. Identifying where sharp money is.
- Caveats: bet split data comes from a subset of books; treat as directional, not exact.

**Pinnacle** (pinnacle.com) — Reference only; not a legal betting option in Pennsylvania.
- Covers: sharpest widely-available lines with low margins.
- Pull: the Pinnacle line for a game or major prop as the benchmark "true" price.
- Use for: comparing any US book's price to the market's best estimate on **spreads and totals**.
- Caveat: Pinnacle's sharp reputation does not extend to player props. Its prop limits are tiny and a 2026 line-movement study found its side of a crossed prop market was usually the one giving value away. For props, use Circa (where posted), Kalshi/ProphetX (prediction markets that move first), and the devigged multi-book consensus from OddsJam/Unabated as the benchmark instead.

**Unabated** (unabated.com) — Free tier plus paid.
- Covers: odds screen built by professional bettors (Rufus Peabody, Captain Jack Andrews), devigging calculator, prop screen, CLV tracking, educational content.
- Use for: Factor 1.7. Best single tool for computing a "fair" price from multiple books and measuring closing-line value.

**Covers** (covers.com) — Free.
- Covers: consensus picks, ATS and O/U trends, matchup pages, forum.
- Pull: historical ATS records in specific situations (e.g., home underdogs after a loss).
- Caveats: trend data is easy to over-fit. Any trend with fewer than ~50 games is noise.

### 2.2 Player Prop Research (hit rates, line-specific history)

**PropFinder** (propfinder.app) — Paid.
- Covers: browser-based prop research for NFL, NBA, MLB, NHL. Player dashboards, hit rate vs. a given line, matchup pages, live odds.
- Pull: hit rate over last 5/10/20 games, home/away splits, hit rate vs. specific opponent, minutes/snaps trends.
- Use for: Factors 1.2, 1.3. Fast triage of which props have a strong recent hit rate at the current line.

**Outlier** (outlier.bet) — Paid, iOS-first.
- Covers: prop hit-rate charts, custom line builder (set your own alt line and see hit rate), alt-line odds shopping across books, correlation tools for parlays.
- Pull: hit rate at the exact line you're considering, best alt-line price across books, correlated-leg suggestions.
- Use for: building same-game parlays with positively correlated legs; finding alt lines where the price is better than the hit rate suggests.

**LineMate** (linemate.io) — Free tier plus paid.
- Covers: prop trends, hit rates, and a strong NHL/NBA focus.
- Pull: same as above; useful as a second opinion.

**Important note on hit rates:** a hit rate is a *starting point, not a conclusion*. A 9-of-10 hit rate over a line means the books have likely already moved the line up. Always ask *why* the player hit (minutes, opponent, game script) and whether those conditions repeat tonight. Never bet a hit rate without checking availability and matchup for the specific game.

### 2.3 Raw Statistics and Advanced Metrics (the ground truth)

**Pro Football Reference** (pro-football-reference.com) — Free.
- Pull: game logs, splits (home/away, vs. division, by score margin), snap counts, target and touch counts, team pace (plays per game), penalty rates.

**Basketball Reference** (basketball-reference.com) — Free.
- Pull: game logs, minutes, usage rate, splits (rest days, home/away, by opponent), team pace and rating.

**NBA.com Stats** (nba.com/stats) — Free.
- Pull: pace, usage %, on/off splits, lineup data, tracking data (touches, drives, contested shots).
- Use for: understanding how a player's role changes when a teammate is out (on/off data is the key tool for the redistribution effect in 1.1).

**Cleaning the Glass** (cleaningtheglass.com) — Paid.
- Covers: NBA stats with garbage time removed, which is the most honest view of how a team actually plays.
- Pull: pace, offensive/defensive rating, shot location profiles, opponent-adjusted numbers.
- Use for: Factor 1.2, 1.3. Removing noise from blowouts.

**Baseball Savant** (baseballsavant.mlb.com) — Free.
- Covers: Statcast data for every pitch and batted ball.
- Pull: batter vs. pitcher pitch-type performance, expected stats (xBA, xSLG, xwOBA), barrel rate, pitch mix, platoon splits, sprint speed, park-adjusted data.
- Use for: Factor 1.3. This is the most predictive public data available in any sport for individual props (K props, HR props, total bases).

**FanGraphs** (fangraphs.com) — Free plus paid.
- Pull: projected lineups, daily starting pitcher projections, park factors, bullpen usage logs, umpire data.
- Use for: park factors (1.4), bullpen fatigue (1.3), and daily projections for every player.

**Natural Stat Trick / MoneyPuck** (naturalstattrick.com, moneypuck.com) — Free.
- Covers: NHL advanced stats and game-level win probabilities.
- Pull: expected goals, TOI, power-play deployment, goalie save % above expected, projected goalie starts.

### 2.4 Injury News, Lineups, and Roles

**Rotowire** (rotowire.com) — Free tier plus paid.
- Covers: injury reports, projected lineups, depth charts, news blurbs with analysis, for every sport.
- Pull: latest status, expected role change ("expected to start in place of X"), and projected lineups for MLB/NBA.
- Use for: Factor 1.1. This is usually the fastest aggregated news source.

**Underdog Network / Rotoworld (NBC Sports Edge)** — Free.
- Similar injury and news coverage; useful as a cross-check.

**Official league injury reports:**
- NFL: posted Wed/Thu/Fri and ~90 min before kickoff (inactives).
- NBA: posted throughout the day, must be updated by 5 p.m. ET for that night's games.
- MLB: lineups posted 1–4 hours before first pitch; starting pitchers usually announced days ahead.
- NHL: goalie starters are often confirmed at morning skate; verify before betting.

**Team beat writers on X/Twitter:** frequently the first source for game-time decisions and starting goalies. Search the team name plus "inactives," "starting goalie," or "lineup."

### 2.5 Matchup and Defense-vs-Position Tools

**FantasyPros** (fantasypros.com) — Free plus paid.
- Pull: NFL defense-vs-position rankings, target share, snap share, red-zone usage.

**4for4** (4for4.com) — Paid.
- Covers: NFL projections, a Player Prop Stat Explorer (hit rate vs. a line, filterable by week), and an aggregate projection vs. the posted line.
- Pull: 4for4 projection for a stat vs. the book's line; hit rate excluding games where the player left early.
- Use for: Factor 1.2, 1.3 in the NFL.

**PFF (Pro Football Focus)** (pff.com) — Paid.
- Pull: player grades, coverage schemes faced, pressure rates, matchup-specific grades (e.g., a WR vs. a specific CB).
- Use for: scheme matchups (1.3). Most granular NFL matchup data available publicly.

**Sharp Football / TruMedia** — Paid.
- Advanced NFL play-by-play data: pass rate over expected, play-action rates, tempo.

### 2.6 Weather and Venue

**Weather.gov** (weather.gov) — Free, authoritative.
- Pull: hourly forecast for the stadium's location, especially sustained wind speed, gusts, and precipitation probability at game time.

**RotoGrinders NFL/MLB Weather** (rotogrinders.com/weather) — Free.
- Covers: per-game weather with wind direction relative to the field, roof status for domes.

**Swish Analytics / Ballpark Pal (MLB)** — Free/paid.
- Covers: park-and-weather-adjusted run and HR expectations for every game.

### 2.7 Officiating

**Umpire Scorecards** (umpscorecards.com) — Free.
- Pull: each MLB umpire's strike-zone accuracy and tendency (favors hitters or pitchers). Umpire assignments post the morning of the game.

**NBA Referee Assignments** (official.nba.com/referee-assignments) — Free.
- Cross-reference with referee stats on sites like Covers or Action Network for foul rate and total tendencies.

**NFLPenalties.com** — Free.
- Pull: penalty rates by crew.

---

## Part 3: Recommended Workflow for a Prop or Parlay Card

1. **Start with the schedule and the market.** List the games. Pull opening and current spread/total from Action Network or OddsJam. Note where lines have moved and in which direction.
2. **Check availability first.** Rotowire plus the official injury report. Mark every game where a key player is out, questionable, or on a rest day. Identify who absorbs the vacated volume (NBA.com on/off splits, PFR target share, FanGraphs projected lineups).
3. **Set the game environment.** Pace/tempo for both teams, expected game script from the spread, weather (outdoor only), park factor (MLB), goalie (NHL), umpire (MLB), referee crew (NBA).
4. **Screen candidate props.** Use PropFinder/Outlier/4for4 to pull hit rates at the current line. Keep only props where the environment set in step 3 supports the hit rate continuing (e.g., don't take a receptions over against a man-heavy defense in 25 mph wind just because the hit rate is 8/10).
5. **Verify with raw data.** For each surviving prop, open the game log on the Reference sites or Savant. Confirm the hit rate wasn't inflated by blowouts, garbage time, or games the player left early.
6. **Shop the price.** Use OddsJam/OddsShopper/Outlier to find the best odds or an alt line across all available Pennsylvania books. A half-point or 10 cents of price on every leg compounds.
7. **Build the parlay with correlation in mind.** Positively correlated legs (QB passing yards + WR1 receiving yards; NBA game over + star points over; MLB team total + leadoff hitter total bases) are the only place a parlay's math works in the bettor's favor. Books price some correlation into same-game parlays; compare the SGP price to the product of the individual leg prices to see how much is being taken.
8. **Record everything.** Log each leg with the price taken, closing line, and result. Closing-line value (CLV), meaning whether the line moved in your favor after you bet, is the best long-run measure of whether the process is working, independent of short-term results.

---

## Part 4: Rules That Prevent Common Mistakes

- **Never treat a hit rate as a probability.** Adjust for the specific game's conditions every time.
- **Small samples lie.** Fewer than ~10 games for a player trend, fewer than ~50 games for a team trend, and the number is mostly noise.
- **The market is usually right.** If a price looks wildly off, assume there is news you haven't seen and go find it before betting.
- **Injury timing beats analysis.** The edge from being first to a lineup change is larger than the edge from any model. Check news within 30 minutes of tip/kickoff/first pitch.
- **Every parlay leg pays the book's margin.** A four-leg parlay of standard -110 legs gives the book roughly 4x the edge it gets on a single bet. Only include legs with an identified reason to believe the true probability exceeds the implied probability.
- **Correlation can be negative too.** A team's spread cover and a specific opponent player's over are often in tension. Check both directions.
- **Weather only matters outdoors, and wind matters most.** Confirm roof status before applying weather to any game.
- **Don't chase narrative factors.** Revenge games, "must-win" framing, and streaks are mostly priced in or irrelevant. Availability, pace, matchup, and price are where the measurable edge lives.
- **Bankroll discipline.** Parlays and props are high-variance products. Stake sizing should assume long losing runs are normal.

---

## Part 5: NFL Focus — Analysts, Accounts, and Extra Data Sources

This section is NFL-specific. The agent should treat analysts as **inputs to its own process**, not as picks to copy. Use them to (a) learn what the market is reacting to, (b) catch information early, and (c) borrow reasoning frameworks. Any claimed win rate should be treated as marketing until independently tracked.

### 5.1 How to use analysts (three tiers)

| Tier | What they provide | How the agent should use them |
|---|---|---|
| **News breakers** | Injuries, inactives, lineup changes, minutes before anyone else | Factor 1.1. Set alerts. Act on the information, not on their opinion. |
| **Analysts / modelers** | Public reasoning, pace/scheme data, projections, matchup breakdowns | Factors 1.2–1.4. Steal the framework and the data; form your own number. |
| **Prop specialists / market readers** | Which props are mispriced, where sharp money went, line-move explanations | Factor 1.7. Cross-check against your own price. If you agree *and* the price is still there, that's a signal. If they moved the line already, the edge is gone. |

### 5.2 News breakers (fastest injury and inactive info)

- **Adam Schefter** (ESPN, @AdamSchefter) and **Ian Rapoport** (NFL Network, @RapSheet): national breaking news. First on major injuries, trades, and game-time decisions.
- **Tom Pelissero** (NFL Network, @TomPelissero) and **Jordan Schultz** (@Schultz_Report): second wave of national insiders; frequently first on secondary players.
- **Team beat writers** for both teams in any game you're betting. They post practice participation, "limited/DNP" designations, and pregame warmup observations that precede the official inactive list by 30–60 minutes. For the Steelers: Mike DeFabo (The Athletic), Brooke Pryor (ESPN), Gerry Dulac (Post-Gazette). Build the equivalent list for every team.
- **Official NFL injury reports**: Wednesday/Thursday/Friday practice reports, plus inactives ~90 minutes before kickoff. Available via NFL.com, team sites, and Rotowire.
- **Rotowire NFL / Underdog Network NFL**: aggregated feeds of the above with a line of analysis on what the change means for volume.

### 5.3 Analysts and modelers (reasoning and data)

- **Warren Sharp** (Sharp Football Analysis, @SharpFootball): scheme, tempo, play-calling tendencies, early-down pass rates, and weekly game previews. Publishes an annual 600-page preview with team-by-team analysis, forecasted lines, and unit rankings. His totals-focused approach maps directly to Factors 1.2 and 1.3. Paid subscription for picks; free content is substantial.
- **Ben Baldwin** (@benbbaldwin, rbsdm.com): creator of nflfastR and rbsdm.com, which provide free EPA, success rate, pass rate over expected, and team efficiency tables. The best free source for "how good is this offense/defense really" beyond yards and points.
- **Evan Silva and Adam Levitan** (Establish The Run, @evansilva / @adamlevitan): weekly matchup breakdowns, target/touch projections, and a "props I bet" column. Levitan's prop process (projection vs. line, identify the reason for the gap, bet only with a clear catalyst) is a good template for the agent.
- **Scott Barrett and Dwain McFarland** (Fantasy Points, @ScottBarrettDFB / @dwainmcfarland): usage and route data, "Fantasy Points Data" tool with route participation, target-per-route-run, and coverage splits. Strong for receptions/receiving yards props.
- **PFF NFL** (@PFF): coverage grades, pressure rates, WR/CB matchup grades. Paid.
- **Ian Wharton** (@NFLFilmStudy): film-based analysis of scheme changes and personnel; useful for identifying role shifts before the box score shows them.
- **Aaron Schatz** (FTN Fantasy, @FO_ASchatz): DVOA (opponent-adjusted efficiency), now hosted at FTN. Good for weighting matchup strength.
- **Nate Tice** (Yahoo, @Nate_Tice) and **Sam Monson / Steve Palazzolo** (Check the Mic podcast): scheme-focused explainers on why an offense or defense is performing the way it is.

### 5.4 Prop specialists and market readers

- **PropBetGuy** (@PropBetGuy, SportsLine/VSiN): transparent, prop-only bettor with a public record across NFL and other sports; typical stake is one unit. Useful for seeing which NFL props sharp prop bettors are targeting and why.
- **Rufus Peabody** (@RufusPeabody, Unabated): professional bettor; publishes his NFL power ratings and explains how he prices games. His process (build a number, compare to market, bet the gap) is the reference standard.
- **Gill Alexander** (@beatingthebook, VSiN "A Numbers Game"): daily discussion of line movement and why numbers moved.
- **Ben Fawkes** (@BFawkesESPN): reports betting action at national and Las Vegas books, including where big money landed.
- **Bill Krackomberger** (@BillKrackman): professional bettor, value-focused; often flags soft numbers.
- **Ariel Epstein** (@ArielEpstein, Fanatics Sportsbook / "Prop Queen"): NFL prop coverage aimed at a broader audience; useful for spotting which props are getting public attention (and therefore likely to move against the public side).
- **Action Network NFL team** (@ActionNetworkHQ): line-movement alerts, bet%/money% splits, and "sharp report" posts before Sunday.

### 5.5 Additional NFL data sources not covered in Part 2

- **rbsdm.com** (free): EPA/play, success rate, pass rate over expected, and QB efficiency, updated after every game. Use for matchup strength (1.3) and pace/pass tendencies (1.2).
- **NFL Next Gen Stats** (nextgenstats.nfl.com, free): separation, time to throw, air yards, expected rushing yards, completion probability. Use for receiver matchup quality and QB pressure handling.
- **Fantasy Points Data** (paid): route participation, targets per route run, coverage splits (man vs. zone production), and red-zone usage. The most direct data for reception and receiving-yard props.
- **PlayerProfiler** (free): snap share, target share, air yards share, opportunity share, in one dashboard per player.
- **FTN Data / DVOA** (paid): opponent-adjusted team and player efficiency.
- **Sumer Sports** (free/paid): team and player analytics with an emphasis on roster construction and scheme.
- **NFL Penalties** (nflpenalties.com, free): crew assignments and flag rates, which affect drive sustainability and pace.
- **Kalshi / ProphetX** (prediction markets): a 2026 study of 600M+ line movements found prediction markets moved first and priced props most accurately. Use their prices as an additional prop benchmark alongside Circa and the devigged book consensus.

### 5.6 NFL weekly cadence for the agent

- **Monday–Tuesday:** review previous week's results and CLV; note early lookahead lines; check Monday injury reports and any MRI news.
- **Wednesday:** first official practice report; opening props post at most books. Pull rbsdm/Next Gen updates. Read Sharp, ETR, and Fantasy Points weekly previews.
- **Thursday–Friday:** practice reports narrow "questionable" designations; props firm up. Identify props where projection and line diverge with a clear catalyst.
- **Saturday:** check weather (Weather.gov, RotoGrinders) and roof status; final line shopping across Pennsylvania books.
- **Sunday morning:** beat-writer updates, pregame warmup reports, inactives at ~11:30 a.m. ET for 1 p.m. games. Re-price any prop touched by an inactive. Bet only after inactives unless the number is clearly moving away.

---

*Compiled September 2026. Site features and pricing tiers change frequently; re-verify a tool's current capabilities before relying on it. Sportsbook availability referenced is for Pennsylvania.*
