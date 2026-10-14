# Dashboard

```bash
streamlit run dashboard/app.py
```

| Section | Page | Purpose |
|---|---|---|
| Build | **Strategy Builder** | Write rules, validate them against data (causal, per-symbol), save as YAML |
| | **Backtest Lab** | Data, strategy, exits, costs and sizing → verdict against the study bar, equity, drawdown, rolling Sharpe, monthly heatmap, trade map, robustness, splits; export an HTML tearsheet or save the run |
| Validate | **Parameter Search** | Fast sweep, whole-search permutation null, PBO, a Sharpe heatmap (a real edge is a plateau, not a peak) |
| | **Walk-Forward** | Rolling or anchored folds, stitched out-of-sample P&L, the parameters each fold chose |
| | **Robustness** | Monte Carlo drawdown and outcome ranges; Reality Check / SPA across saved runs |
| | **Compare Runs** | Saved runs side by side, with their manifests |
| Markets | **Options Lab** | Structures on synthetic or ThetaData chains; the same trades at mid, quarter and natural |
| | **Event Studies** | CAR paths around uploaded, earnings or insider events; trade them through the engine |
| | **Insider Filings** | Purchases by role, cluster buys, a point-in-time view |
| Data | **Data Manager** | Catalog and coverage, file import, public fetchers, quality checks, continuous futures, SQL |
| Governance | **Research Registry** | Each trial against the bar it faces; pre-registration |
| | **Monitoring** | Job heartbeats and data freshness |

The theme follows the viewer's light/dark setting. `tests/test_dashboard.py` renders every page
headlessly in CI and runs the main actions.
