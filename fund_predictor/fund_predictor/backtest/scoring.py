def summarize_performance(trades, win_target: float):
    if trades.empty:
        return {"trade_count": 0, "score": -999}
    returns = trades["return"]
    trade_count = len(trades)
    win_rate_12 = (returns > win_target).mean()
    positive_rate = (returns > 0).mean()
    avg_return = returns.mean()
    take_profit_rate = (trades["exit_reason"] == "take_profit").mean()

    return {
        "trade_count": trade_count,
        "win_rate_12": win_rate_12,
        "positive_rate": positive_rate,
        "avg_return": avg_return,
        "median_return": returns.median(),
        "max_return": returns.max(),
        "min_return": returns.min(),
        "take_profit_rate": take_profit_rate,
        "maturity_rate": (trades["exit_reason"] == "maturity").mean(),
        "avg_hold_days": (trades["sell_date"] - trades["buy_date"]).dt.days.mean(),
        # 强信号占比：用于辅助判断策略是否过度依赖弱信号。
        "strong_signal_rate": (trades.get("intensity_level", "none") == "strong").mean() if "intensity_level" in trades else 0.0,
    }


def score_strategy(metrics: dict, m: int, n: int, cfg: dict, recent_validation_score: float = 0.0):
    if metrics.get("trade_count", 0) == 0:
        return -999
    sc = cfg["scoring"]
    score = (
        metrics["win_rate_12"] * 0.45
        + metrics["positive_rate"] * 0.20
        + metrics["avg_return"] * 0.25
        + metrics["take_profit_rate"] * 0.05
        + recent_validation_score * 0.05
        + metrics.get("strong_signal_rate", 0.0) * 0.03
    )
    penalty = 0.0
    if m >= 15:
        penalty += sc["penalty_m_ge_15"]
    if n <= 7:
        penalty += sc["penalty_n_le_7"]
    if metrics["trade_count"] < cfg["strategy"]["min_trades"] * 1.5:
        penalty += 0.02
    return score - penalty
