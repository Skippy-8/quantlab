import numpy as np
import pandas as pd

from quantlab.data.synthetic import panel
from quantlab.engine import EngineConfig, check_no_lookahead, evaluate, prepare
from quantlab.events import event_strategy, event_study


def planted(drift=0.01, n_events=40, seed=0):
    """Daily panel where each event is followed by `drift` per day of abnormal return for 5 days."""
    df = panel(n_bars=500, symbols=("A", "B", "C", "D", "E"), freq="D", vol=0.01, seed=seed)
    rng = np.random.default_rng(seed)
    ev = []
    for _ in range(n_events):
        sym = rng.choice(["A", "B", "C", "D", "E"])
        k = int(rng.integers(150, 480))
        ts = df[df.symbol == sym]["timestamp"].iloc[k]
        ev.append((sym, ts))
        mask = (df.symbol == sym) & (df.timestamp >= ts)
        bump = np.ones(mask.sum())
        bump[:5] = 1 + drift * np.arange(1, 6)
        bump[5:] = 1 + drift * 5
        for c in ("open", "high", "low", "close", "bbo_bid", "bbo_ask"):
            df.loc[mask, c] *= bump
    return df, pd.DataFrame(ev, columns=["symbol", "timestamp"])


def test_event_study_recovers_a_planted_drift():
    df, ev = planted()
    out = event_study(df, ev, pre=3, post=10, model="market")
    assert out["events"] >= 30
    assert out["mean_car_post"] > 0.01 and out["t_date_clustered"] > 3
    path = out["path"]
    assert path.loc[path["bar"] == -1, "mean_car"].abs().iloc[0] < 0.01      # nothing before the event


def test_event_study_on_random_dates_finds_nothing():
    df, _ = planted(drift=0.0)
    rng = np.random.default_rng(5)
    days = df["timestamp"].drop_duplicates().iloc[150:480].to_list()
    ev = pd.DataFrame({"symbol": rng.choice(list("ABCDE"), 40), "timestamp": rng.choice(days, 40)})
    assert abs(event_study(df, ev, pre=3, post=10)["t_date_clustered"]) < 3


def test_event_strategy_is_causal_and_profits_from_the_drift():
    df, ev = planted()
    fn = event_strategy(ev, side=1, hold=5)
    assert check_no_lookahead(fn, prepare(df))
    res = evaluate(fn, df, EngineConfig(days_per_year=252))
    assert res.summary["trades"] >= 20 and res.summary["mean_net_bp_per_trade"] > 0


def test_market_model_needs_an_estimation_window():
    df, ev = planted()
    out = event_study(df, ev, pre=3, post=10, model="market_model", estimation=60)
    assert out["events"] > 0 and np.isfinite(out["mean_car_post"])
