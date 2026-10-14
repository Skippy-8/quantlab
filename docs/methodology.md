# Methodology

This document explains the choices quantlab makes on a researcher's behalf, and why.

## 1. Execution: how a signal becomes a fill

A strategy returns a position in {-1, 0, +1} for each bar: the position it wants **after** that
bar's close. The engine turns it into orders:

| Event | Rule | Why |
|---|---|---|
| Entry / exit order | A limit on its own side of the book: buy at the bid, sell at the ask; re-pegged each close | Never crossing the spread is the most favourable execution a strategy can claim, so the engine makes it earn the fill |
| Fill | Only when a **later** bar trades **strictly through** the limit (`low < bid`, `high > ask`) | Touching a price says nothing about queue position; counting touches as fills is a classic source of phantom P&L |
| Unfilled entry | Cancelled after `entry_ttl_bars`, counted as a miss, never booked | Missed trades are adverse-selected; ignoring them flatters the fill rate |
| Unfilled exit | Crosses the spread after `exit_ttl_bars` and pays the taker fee | A position must always be closable |
| Funding | Every settlement the position is open through is booked as `-side × rate` | Perpetual-futures carry can dominate a slow strategy's P&L |
| Missing quotes | `close ∓ assumed_half_spread_bp`, flagged in the summary | Honest about the assumption rather than silently assuming a zero spread |

P&L is in basis points of notional, one unit per trade, so strategies with different turnover are
comparable before any sizing decision.

## 2. Integrity checks

`evaluate()` runs both checks before computing anything:

- **Truncation invariance.** The panel is cut at 50%, 70% and 90% of its timestamps. Every signal at
  or before the cut must be identical to the signal computed on the full panel. This catches
  `shift(-k)`, centred rolling windows, back-fill, and any statistic computed over the whole sample
  (a z-score against the full-period mean is the most common case).
- **Symbol-order invariance.** The symbol blocks are reversed; every signal must stay the same.
  This catches rolling or differencing operations applied without `groupby("symbol")`, where one
  symbol's last rows feed the next symbol's first.

Both raise `LookaheadError` naming the exact symbol and timestamp that changed.

## 3. Statistics that do not flatter

- **Day t.** The t-statistic of the daily P&L series (days that traded), not of individual trades:
  trades on the same day are not independent.
- **Calendar Sharpe.** Annualised over every calendar day, including flat ones. A Sharpe computed
  only over days with trades overstates a strategy that is mostly flat.
- **Calendar halves.** The mean of the first and second half of the sample, reported separately. A
  result whose sign flips between halves is a regime, not an edge.
- **Symbol-clustered bootstrap.** Symbols are resampled with all their trades. The result must
  have P(mean > 0) ≥ 95%, a positive median trade, and a positive mean with the five best symbols
  removed, so a result carried by one or two names does not pass.

## 4. Multiple testing

**The trial registry** records every run under a study name. K is the number of distinct trials
(same strategy, parameters, data fingerprint and window = one trial). Two consequences:

1. **The pass bar rises with K.** The best of K pure-noise trials is expected to reach
   |t| ≈ √(2 ln K) (the minimum-backtest-length bound of Bailey et al.). A study must clear
   `max(2.0, √(2 ln K))`: 2.0 at K = 7, 2.6 at K = 30, 3.0 at K = 90.
2. **The deflated Sharpe uses every trial.** DSR evaluates the probabilistic Sharpe ratio against
   SR\*, the Sharpe a skill-less best-of-K is expected to reach given the dispersion of all the
   study's trial Sharpes. Skew and kurtosis enter the standard error, so negatively skewed,
   fat-tailed return streams (stopped-out strategies, short options) are not flattered.

**The whole-search permutation null** answers "is the best cell of my sweep better than the best
cell of the same sweep on data with no signal?". Each symbol's signal series is circularly shifted
against its prices. That keeps the signal's autocorrelation, turnover and long/short balance, and
keeps the price path, but destroys any timing relationship. The p-value is the share of shuffled
searches whose *best* cell beats the real best cell.

Also available: Holm (family-wise) and Benjamini-Hochberg-Yekutieli (FDR under arbitrary
dependence) corrections, and the Harvey-Liu Sharpe haircut. The haircut reproduces the paper's
worked example: SR 0.92 over 20 years at 200 trials becomes about 0.44.

## 5. The sealed vault

A held-out period stays out of sample only if nobody looks at it. `quantlab vault seal <dir>`
hashes every file into a manifest, writes a marker, and makes the files read-only. From then on:

- any read under that directory, including through the lake, raises `VaultError` unless a vault
  run is open;
- a run is opened only with a written spec file, whose hash is logged; the **same spec can never be
  run twice**;
- a run refuses to open if any file's hash has changed since sealing;
- every run's start, end and headline result are appended to the vault's register, so the number
  of times the vault has been consulted is always known.

The intended workflow: develop on the in-sample period with the registry counting trials, write a
pre-registration (hypothesis, exact rule, statistic, pass threshold) **before** opening the vault,
register it, run once, and report the result whatever it is.

## 6. Point-in-time insider data

SEC Forms 3/4/5 report insider transactions, but a transaction dated Monday may not be public until
Wednesday evening. The pipeline stores the EDGAR **acceptance timestamp** with every row, and all
read helpers filter on it. `InsiderStore.as_of(ts)` returns exactly what the market could have known
at `ts`. Rows also carry the reporting owner's role and the Rule 10b5-1 flags (the form checkbox
from April 2023, plus whether the row cites a 10b5-1 footnote). Pre-planned trades carry little
information (Cohen, Malloy & Pomorski 2012), so the explorer excludes them by default.
