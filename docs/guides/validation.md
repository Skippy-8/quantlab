# Validation and overfitting

| Question | Tool |
|---|---|
| Is this one result above noise, given how many things I tried? | Trial registry: `|t| ≥ max(2, √(2 ln K))`, deflated Sharpe |
| Is the best cell of my sweep better than the best cell of a sweep on shuffled signals? | `stats.permutation.search_null` |
| How often does the in-sample winner lose out of sample? | `validation.pbo` (CSCV) |
| Does re-optimising on the past work on the unseen future? | `validation.walk_forward` |
| Is the best of a whole set of strategies better than zero after the search? | `validation.reality_check` (White's RC, Hansen's SPA) |
| What range of drawdowns could these trades have produced? | `validation.monte_carlo` |
| Does it hold on data nobody has looked at? | `research.vault` |

## Walk-forward

```python
from quantlab.validation import walk_forward
grid = [{"fast": f, "slow": s} for f in (10, 20, 50) for s in (100, 200)]
wf = walk_forward(sma_crossover, grid, df, train_days=120, test_days=30)
wf.folds          # each fold's chosen parameters, in-sample score, out-of-sample P&L
wf.oos_daily      # only the unseen windows, stitched
```

Each fold chooses in fast mode on its training window, then the full engine scores the choice on the
next window, using the training window as indicator warm-up only.

## Probability of backtest overfitting

```python
from quantlab import fast, validation
stats, daily = fast.sweep(cells, df)
validation.pbo(daily)["pbo"]      # share of splits where the IS winner is below median OOS
```

The sample is cut into blocks; for every way of picking half of them as in-sample, the best
configuration is chosen in-sample and ranked out of sample (Bailey, Borwein, López de Prado & Zhu,
2017). A PBO near 50% or above means the selection is not carrying information forward.

## Reality Check and SPA

```python
validation.reality_check(daily_returns_by_strategy)   # {'reality_check_p': ..., 'spa_p': ...}
```

A stationary bootstrap (Politis & Romano) keeps the returns' serial dependence. The SPA version
studentises and removes clearly bad strategies from the null, so a few terrible variants cannot hide
a good one.

## The sealed vault

```bash
quantlab vault seal data/vault          # hash every file, write a marker, make them read-only
```

```python
from quantlab.research.vault import open_run
with open_run("data/vault", spec="prereg/momentum.md", hypothesis="12-1 momentum") as run:
    res = evaluate(strategy, run.read("klines_1h.parquet"))
    run.result(res.summary)
```

A run opens only for a written spec; the same spec can never run twice; any file changed since sealing
blocks the run; every start, end and headline result is appended to the vault's register.
