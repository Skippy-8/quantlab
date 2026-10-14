# Scheduling and monitoring

Silence is ambiguous: a stalled pipeline and a quiet market look the same. So every scheduled job
writes heartbeats:

```python
from quantlab import monitor
with monitor.job("fetch_binance", symbols=3):     # 'start', then 'ok' or 'error' with the exception
    ...
```

and a health check turns heartbeats and data freshness into a status:

```bash
quantlab monitor --job fetch_binance=24 sec_sync=84 --data binance/klines_1h=36
```

| Status | Meaning |
|---|---|
| `OK` | the last run succeeded within its interval × 1.5, or the newest bar is within its allowed age |
| `STALE` | no success within the window, or the data is older than allowed |
| `FAILING` | the last run raised |
| `NEVER_RAN` / `MISSING` | no successful heartbeat yet / the dataset is not in the lake |

The command exits non-zero when anything is not `OK`, so cron, systemd (`OnFailure=`) or CI can alert
on the exit code alone. `deploy/` has example units: a daily data refresh and an hourly health check.
