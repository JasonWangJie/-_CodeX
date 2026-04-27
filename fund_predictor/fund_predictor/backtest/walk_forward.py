from datetime import timedelta
import json
from pathlib import Path

import pandas as pd

from fund_predictor.backtest.grid_search import run_grid_search
from fund_predictor.backtest.scoring import score_strategy, summarize_performance
from fund_predictor.backtest.simulator import simulate_trades
from fund_predictor.features.signals import add_signals


def run_walk_forward(df: pd.DataFrame, cfg: dict, fund_code: str) -> list[dict]:
    if len(df) < 600:
        return []
    out = []
    date_col = pd.to_datetime(df["nav_date"])
    start = date_col.min() + pd.DateOffset(years=3)
    end = date_col.max() - pd.DateOffset(months=6)
    cursor = start
    while cursor <= end:
        train_start = cursor - pd.DateOffset(years=3)
        train_end = cursor - timedelta(days=1)
        valid_end = cursor + pd.DateOffset(months=6) - timedelta(days=1)

        train_df = df[(date_col >= train_start) & (date_col <= train_end)]
        valid_df = df[(date_col >= cursor) & (date_col <= valid_end)]
        if train_df.empty or valid_df.empty:
            cursor += pd.DateOffset(months=6)
            continue

        best = run_grid_search(train_df, cfg)
        if not best:
            cursor += pd.DateOffset(months=6)
            continue

        # 使用训练阶段最优参数在验证窗口上独立评估，避免把训练分数误当验证分数。
        valid_sig = add_signals(valid_df, best["r1_floor"], best["r2_floor"], cfg)
        valid_trades = simulate_trades(valid_sig, best["m"], best["n"], cfg)
        valid_metrics = summarize_performance(valid_trades, cfg["strategy"]["win_target"])
        if valid_metrics.get("trade_count", 0) > 0:
            valid_score = score_strategy(valid_metrics, best["m"], best["n"], cfg)
            valid_trade_count = int(valid_metrics["trade_count"])
        else:
            valid_score = -999
            valid_trade_count = 0

        record = {
            "fund_code": fund_code,
            "train_start": str(train_start.date()),
            "train_end": str(train_end.date()),
            "valid_start": str(cursor.date()),
            "valid_end": str(valid_end.date()),
            "best_m": best["m"],
            "best_n": best["n"],
            "r1_floor": best["r1_floor"],
            "r2_floor": best["r2_floor"],
            "train_score": best["score"],
            "valid_score": valid_score,
            "valid_trade_count": valid_trade_count,
        }
        out.append(record)
        cursor += pd.DateOffset(months=6)
    return out


def append_tuning_history(records: list[dict], meta_dir: str) -> None:
    if not records:
        return
    Path(meta_dir).mkdir(parents=True, exist_ok=True)
    path = Path(meta_dir) / "tuning_history.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
