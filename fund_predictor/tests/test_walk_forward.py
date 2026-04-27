import pytest

pd = pytest.importorskip("pandas")


from fund_predictor.backtest import walk_forward


def _dummy_cfg():
    return {
        "strategy": {"win_target": 0.12},
        "scoring": {},
        "feature": {"accel_min": 1.0},
        "enhancement": {},
    }


def _dummy_df(days=1400):
    return pd.DataFrame({"nav_date": pd.date_range("2020-01-01", periods=days, freq="D")})


def test_walk_forward_uses_independent_validation_score(monkeypatch):
    monkeypatch.setattr(
        walk_forward,
        "run_grid_search",
        lambda train_df, cfg: {"m": 3, "n": 5, "r1_floor": 1.0, "r2_floor": 1.0, "score": 0.88, "metrics": {"trade_count": 9}},
    )
    monkeypatch.setattr(walk_forward, "add_signals", lambda valid_df, r1, r2, cfg: valid_df)
    monkeypatch.setattr(walk_forward, "simulate_trades", lambda sig_df, m, n, cfg: pd.DataFrame({"x": [1, 2]}))
    monkeypatch.setattr(walk_forward, "summarize_performance", lambda trades, win_target: {"trade_count": 2})
    monkeypatch.setattr(walk_forward, "score_strategy", lambda metrics, m, n, cfg: 0.31)

    records = walk_forward.run_walk_forward(_dummy_df(), _dummy_cfg(), "000001")

    assert records
    assert records[0]["train_score"] == 0.88
    assert records[0]["valid_score"] == 0.31
    assert records[0]["valid_score"] != records[0]["train_score"]
    assert records[0]["valid_trade_count"] == 2


def test_walk_forward_sets_default_when_validation_has_no_trades(monkeypatch):
    monkeypatch.setattr(
        walk_forward,
        "run_grid_search",
        lambda train_df, cfg: {"m": 3, "n": 5, "r1_floor": 1.0, "r2_floor": 1.0, "score": 0.88, "metrics": {"trade_count": 9}},
    )
    monkeypatch.setattr(walk_forward, "add_signals", lambda valid_df, r1, r2, cfg: valid_df)
    monkeypatch.setattr(walk_forward, "simulate_trades", lambda sig_df, m, n, cfg: pd.DataFrame())
    monkeypatch.setattr(walk_forward, "summarize_performance", lambda trades, win_target: {"trade_count": 0})

    records = walk_forward.run_walk_forward(_dummy_df(), _dummy_cfg(), "000001")

    assert records
    assert records[0]["valid_score"] == -999
    assert records[0]["valid_trade_count"] == 0
