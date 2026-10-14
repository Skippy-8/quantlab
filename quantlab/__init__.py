"""quantlab: a research platform for honest backtests.

The pieces, in the order a study uses them:

* ``quantlab.data``      - a Parquet lake with a DuckDB catalog, public-data fetchers, synthetic data.
* ``quantlab.engine``    - the standardized scoring engine (fills, fees, funding, lookahead checks).
* ``quantlab.stats``     - deflated Sharpe, multiple-testing corrections, permutation nulls, intervals.
* ``quantlab.research``  - the trial registry (counts every test), the sealed vault, standard splits.
* ``quantlab.sec``       - a point-in-time SEC Form 3/4/5 insider-transaction pipeline.
* ``quantlab.monitor``   - heartbeats and data-freshness checks for scheduled jobs.
"""
from quantlab.engine import EngineConfig, LookaheadError, evaluate, run_backtest

__all__ = ["EngineConfig", "LookaheadError", "evaluate", "run_backtest"]
__version__ = "0.1.0"
