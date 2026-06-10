# IMC Prosperity 4

> *From April 14 to April 30, more than **18,803 teams** ventured into deep space, working hard to
> code and trade their way to Prosperity. For five exciting rounds they gave it their all in an
> attempt to be crowned IMC Trading Talent of 2026.*

This repository is my post-competition archive and writeup for IMC Prosperity 4 (2026), IMC
Trading's global algorithmic-and-manual trading challenge for university students. I competed
solo, and this is the story of how it went -- the strategies I deployed each round, what I
learned, and where I landed.

## Results

Competing alone against a field of **18,803+ teams**, I finished:

| Category | Result |
|---|---|
| **Overall** | **Top 7%** |
| Algorithmic trading | **Top 8.3%** |
| Manual trading | **Top 6.5%** |
| United States rank | **#356** |

Overall I was satisfied with this outcome: a top-7% global finish and nearly a top-350 placement in the US, achieved as  a solo competitor.

## How Prosperity works

Prosperity is a simulated trading game built by IMC traders, quants, and engineers. It ran for 16
days, split into two phases with a short intermission. Before the scored rounds, a **tutorial
round** let you practice on two dummy products (`EMERALDS`, the stable one, and `TOMATOES`, the
volatile one) and learn the platform.

Each of the **five scored rounds** had two independent challenges:

- **Algorithmic challenge** -- you write a Python `Trader` class that the exchange calls on every
  tick of a simulated market. It sees the current order book and your positions, and returns the
  orders to place. The same code runs across multiple simulated days; open positions are
  liquidated against a hidden fair value at the end. Your only memory between ticks is a string you
  serialize and hand back (`traderData`).
- **Manual challenge** -- a self-contained math/optimization puzzle (auctions, budget allocation,
  option pricing, news-driven portfolios) submitted through the web UI.

The narrative gave it flavor: my crew, sent by the *eXtended Interplanetary Resource Exchange
Network (XIREN)*, set up a trading outpost on the arid planet Intara (rounds 1–2), then was
invited to the Great Orbital Ascension Trials (GOAT) on the prosperous planet *Solvenar*
(rounds 3–5) to compete for the title of Trading Champion of the Galaxy. The GOAT phase reset the
leaderboard to zero and swapped out every product. The currency throughout is the *XIREC*.

---

## The five rounds

The P&L figures below come from my captured submission logs (`roundN/*.log`) and are meant to show
which legs of each strategy actually carried the weight, not as official leaderboard totals.

### Round 1 -- "Trading Groundwork"

**Synopsis.** Landing on Intara, the first goods on the exchange were **Ash-Coated Osmium**
(`ASH_COATED_OSMIUM`) and **Intarian Pepper Root** (`INTARIAN_PEPPER_ROOT`), each with a position
limit of 80. Osmium was hinted to be volatile but with a "hidden pattern"; Pepper Root was a steady,
slow-growing product. The manual challenge, *An Intarian Welcome*, was a sealed-bid auction on two
one-off goods (`DRYLAND_FLAX`, `EMBER_MUSHROOM`) with a guaranteed fixed-price buyback afterward --
a clean optimization of bid price against the auction's volume-maximizing clearing rule.

**My algorithm (`round1/round1.py`).** Two products, two distinct treatments:
- **Ash-Coated Osmium** turned out to mean-revert hard around a fixed fair value of **10,000**
  (lag-1 autocorrelation ≈ −0.49). I ran a market-making loop: aggressively *take* any ask below or
  bid above fair, then *make* by quoting just inside the spread, with an inventory fence that stops
  quoting the wrong side as I approach the ±80 limit.
- **Intarian Pepper Root** behaved like the tutorial's stable `EMERALDS`. Its fair value was a
  slowly-drifting EMA base plus a tiny deterministic drift (`0.001 × t`). Since it barely moved
  against me, the winning move was simply to accumulate the maximum long (80) and let
  mark-to-market do the work, sweeping cheap asks and posting a passive bid for the rest.

Pepper Root (~7.3k) was the workhorse; Osmium MM added ~2.5k in the captured run.

### Round 2 -- "Growing Your Outpost"

**Synopsis.** Same two products, but the market got more competitive and a new wrinkle appeared:
the **Market Access Fee (MAF)**. By adding a `bid()` method to my `Trader`, I bid (blind) for *25%
extra order-book flow*. The top 50% of all teams' bids win the extra volume and pay what they bid,
deducted from round P&L -- pure game theory: you only need to clear the median, not top it. The
manual challenge, *Invest & Expand*, allocated a 50,000 budget across three pillars (Research,
Scale, Speed) to maximize `PnL = (Research × Scale × Speed) − Budget_Used`, where Speed was
rank-based against every other player.

**My algorithm (`round2/round2.py`).** The trading logic is the proven Round 1 code, carried
forward, plus a `bid()` returning **205** to compete for the extra market access. The reasoning: my
edge was real and scaled with flow, so paying a modest, median-clearing fee for 25% more volume was
worth it. Performance held steady (~8.5k in the log), again led by Pepper Root. This turned out to be a mistake and my proceeds from the algorithmic round decreased from round 1 to round 2 (i.e. ~96k to ~81k).

### Round 3 -- "Gloves Off" (GOAT begins)

**Synopsis.** New planet, new products, leaderboard wiped. I now traded three things: Hydrogel
Packs (`HYDROGEL_PACK`), Velvetfruit Extract (`VELVETFRUIT_EXTRACT`), and ten Velvetfruit
Extract Vouchers (`VEV_4000` … `VEV_6500`) -- these vouchers are European call options on
Velvetfruit at ten strikes, expiring 7 days from round 1 (so 5 days left at the start of round 3).
This round introduced a new asset class: options. The manual challenge, *The Celestial Gardeners' Guild*, was
a two-bid reserve-price game against hidden counterparties (reserves uniform 670–920 in steps of 5)
with a resale at 920 -- a classic expected-value optimization with a penalty on the second bid.

**My algorithm (`round3/round3.py`).** A three-pronged approach:
- **Velvetfruit Extract** (the option underlying, `S`): a delta-1 market maker around a ~5,250
  anchor, with an EMA-tracked fair value that's gently pulled back to the anchor to resist
  trend-chasing. This was the single biggest earner (~3.2k in the log).
- **Hydrogel Pack**: a standalone market maker priced off a microprice (volume-weighted mid)
  rather than a fixed level, because the price does a random walk within a session, so any fixed fair
  value becomes an accidental directional bet. Edges scale to the live half-spread, with inventory
  skew and a hard cap.
- **Vouchers (options)**, split by moneyness: the deep in-the-money `VEV_4000/4500` were priced by
  pure intrinsic-value arbitrage (`max(S − K, 0)`); the near-the-money `VEV_5000`--`VEV_5500`
  were priced with a from-scratch Black-Scholes call (no SciPy -- `math.erf` for the normal CDF)
  using per-strike implied vols I calibrated (~1.27%/day); the far out-of-the-money
  `VEV_6000/6500` had no exploitable edge that I observed (mid stuck at 0.5) and were skipped.

### Round 4 -- "The More The Merrier"

**Synopsis.** Same three products, but now the Frontier Trade Watch disclosed counterparty
identities -- the `buyer`/`seller` fields on each trade, previously always `None`, now named who
you traded against. The intended edge was to profile counterparties and trade with the ones who consistently win and against the ones that consistently lose. The manual challenge, *Vanilla Just Isn't Exotic Enough*, was a standalone exotic-options
book on `AETHER_CRYSTAL` (simulated as zero-drift GBM at 251% annualized vol): vanilla 2- and 3-week
calls/puts plus a **Chooser**, a **Binary Put**, and a **Knock-Out Put**, held to expiry and scored
as mean P&L over 100 simulations. This was the most quantitatively demanding manual round of the contest and could have significant ramifications for the leaderboard.

**My algorithm (`round4/round4.py`).** I carried the Round 3 algorithm forward unchanged and put my
time into the (heavily weighted) exotic-options manual challenge. It still earned (~5.4k in the log, again led
by Velvetfruit), but in hindsight this round is my clearest example of leaving algorithmic edge on
the table: (1) the newly-revealed counterparty IDs -- the new feature in the round -- went unused, because I couldn't find any obvious indicators and (2) the carried-over code still assumed 5 days to expiry when Round 4 actually had 4, so the
Black–Scholes vouchers were priced with a one-day-stale time-to-expiry. That was a mistake I didn't catch until after the round ended.

### Round 5 -- "The Final Stretch"

**Synopsis.** Everything reset again: 50 brand-new products, in 10 themed groups of 5 (Galaxy
Sounds Recorders, Sleeping Pods, Microchips, Purification Pebbles, Domestic Robots, UV-Visors,
Instant Translators, Construction Panels, Oxygen Shakes, Snack Packs). Old products could no longer
be traded, and the position limit was a tight 10 per product. Some groups hid strong, learnable
price patterns, while others were traps. The manual challenge, *Extra! Extra!*, gave access to a fictional news feed
(*Ashflow Alpha*) to build a one-day hold portfolio on the Ignith exchange, with a convex trading
fee that punished concentration -- a news-comprehension and position-sizing exercise.

**My algorithm (`round5/round5.py`).** With 50 products and a tiny limit, this was a
trend-following "cherry-picking" strategy, not market making. I bucketed every product into
three tiers from sample-day analysis:
- **Tier 1 (hardcoded directions):** ~11 products that trended the same way on all three sample
  days -- take the max position (±10) immediately at the open.
- **Tier 2 (wait-and-follow):** the bulk of the products -- wait until the mid moves more than 100
  from the day's opening price, then commit fully to that direction and never reverse.
- **Tier 3 (skip):** ~9 products that consistently mean-revert after an initial move, where
  trend-following bleeds money -- don't trade them at all.

I also spotted structural relationships (the `PEBBLES` group sums to exactly 50,000, like an index;
`SNACKPACK` chocolate + vanilla is roughly constant, like a pair) -- noted in the code, though I
ultimately traded on the simpler directional signal. Round 5 was the strongest log (~17.4k across
the 50 names).

---

## What I learned

- **Match the model to the product.** The biggest, most repeated lesson: a fixed fair value works
  beautifully for a mean-reverting product (Osmium) and is actively harmful for a random-walking one
  (Hydrogel), where a microprice/EMA is the right tool. Diagnosing *which regime a product is in*
  before writing a line of strategy was worth more than any single clever trick.
- **Options are their own world.** Building Black–Scholes from scratch (no SciPy on the platform),
  calibrating per-strike implied vol from historical fits, and reasoning about deep-ITM intrinsic
  arbitrage vs. worthless OTM vouchers was the steepest and most rewarding learning curve.
- **Inventory risk management is half the game.** Almost every market-making bug I hit traced back
  to position limits and inventory skew. The pattern that survived -- take, then make, then clamp
  quotes strictly inside the live book with a soft cap -- is reused across every round.
- **Don't copy a strategy forward without re-checking its assumptions.** Round 4 is my cautionary
  tale: reusing Round 3 verbatim ignored both the new counterparty data and a changed
  time-to-expiry. The edge was *available*; I just didn't claim it.
- **As a solo competitor, prioritization is the real constraint.** With two challenges per round and
  no teammates, deciding where the marginal hour paid off most -- the exotic-options manual over a
  marginal algo tweak, for instance -- mattered as much as any strategy itself.

## What was fun

The theme was fun -- Aria's transmissions and the space-related elements of each round. The challenge diversity was also good. The challenge designers clearly put forth a lot of effort in building this competition. It was interesting to work on challenges that were simultaneously a coding problem, a quant problem, and a game-theory problem.

## A note on using Claude

I competed solo, and I used Claude as a force-multiplier throughout -- for strategy ideation
(brainstorming how to price the vouchers, how to bucket the 50 Round 5 products, how to think about
the game theory elements, etc.), for building and refining each submission, and for the tight iterate-test-improve
loop that the platform's fast feedback rewards. Applying AI as a research-and-engineering partner is
a big part of how I managed to keep pace with with the top 10% in a field of more than 18,000 teams. It was a
genuinely cool experience toe experiment with using AI to augment my problem-solving and boost my individual performance.

## Repository layout

```
round1/ … round5/   # per round: the submitted Trader (roundN.py) + captured platform output
                     #   (*.log market data + trades + P&L, *.json sandbox log)
*.md (round1–5,      # saved competition wiki pages: per-round rules (algo + manual),
 storyline, etc.)    #   the storyline, and the platform API reference
CLAUDE.md            # architecture/strategy notes for working in this repo
```

*Congratulations to the winning teams, and a big thank you to IMC for running Prosperity 4.*
