import numpy as np

from fund_predictor.backtest.scoring import score_strategy, summarize_performance
from fund_predictor.backtest.simulator import simulate_trades
from fund_predictor.features.signals import add_signals


def _build_grid(cfg: dict):
    m0, m1 = cfg["strategy"]["buy_delay_range"]
    n0 = cfg["strategy"]["hold_days_min"]
    n1 = cfg["strategy"]["hold_days_max"]
    step = cfg["strategy"]["hold_days_step"]
    m_values = list(range(m0, m1 + 1))
    n_values = list(range(n0, n1 + 1, step))
    if len(m_values) * len(n_values) > cfg["runtime"]["max_grid_combinations_per_fund"]:
        m_values = [0, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 35]
        n_values = [7, 14, 21, 30, 45, 60, 90, 120, 180, 270, 360, 540]
    return m_values, n_values


def run_grid_search(df, cfg: dict):
    min_trades = cfg["strategy"]["min_trades"]
    win_target = cfg["strategy"]["win_target"]
    m_values, n_values = _build_grid(cfg)

    best = None
    for r1_floor in cfg["threshold_scan"]["r1_candidates"]:
        r2_hist = df["R2"].dropna()
        if r2_hist.empty:
            continue
        for q in cfg["threshold_scan"]["r2_quantile_candidates"]:
            r2_floor = float(np.quantile(r2_hist, q))
            sig_df = add_signals(df, r1_floor=r1_floor, r2_floor=r2_floor, cfg=cfg)
            if sig_df["signal"].sum() < min_trades:
                continue
            for m in m_values:
                for n in n_values:
                    trades = simulate_trades(sig_df, m, n, cfg)
                    metrics = summarize_performance(trades, win_target)
                    if metrics["trade_count"] < min_trades:
                        continue
                    score = score_strategy(metrics, m, n, cfg)
                    if best is None or score > best["score"]:
                        best = {
                            "score": score,
                            "m": m,
                            "n": n,
                            "r1_floor": r1_floor,
                            "r2_floor": r2_floor,
                            "metrics": metrics,
                            "trades": trades,
                            "signal_df": sig_df,
                        }
    return best
