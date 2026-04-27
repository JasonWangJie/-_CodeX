import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = df.copy()
    price = out["acc_nav"].fillna(out["unit_nav"])
    out["price"] = price

    windows = cfg["feature"]["r1_windows"]
    r1_cols = []
    for n in windows:
        col = f"R1_{n}"
        out[col] = (price.shift(n) - price) / price.shift(n)
        r1_cols.append(col)
    out["R1"] = out[r1_cols].max(axis=1)

    r2_window = cfg["feature"]["r2_window"]
    rolling_high = price.rolling(r2_window).max()
    out["R2"] = (rolling_high - price) / rolling_high

    daily_ret = price.pct_change()
    out["HV90"] = daily_ret.rolling(cfg["feature"]["hv_window"]).std()

    drop_5 = (price.shift(5) - price) / price.shift(5)
    drop_15 = (price.shift(15) - price) / price.shift(15)
    out["accel"] = (drop_5 / drop_15).replace([np.inf, -np.inf], np.nan)

    q = cfg["feature"]["quantile_level"]
    out["r1_q"] = out["R1"].shift(1).expanding().quantile(q)
    out["r2_q"] = out["R2"].shift(1).expanding().quantile(q)

    # 轻量“市场状态过滤”特征：
    # 使用短均线与长均线关系判断趋势状态，不依赖额外外部指数数据。
    enh = cfg.get("enhancement", {})
    short_w = int(enh.get("regime_short_window", 20))
    long_w = int(enh.get("regime_long_window", 60))
    out["ma_short"] = price.rolling(short_w).mean()
    out["ma_long"] = price.rolling(long_w).mean()
    # 1=趋势偏强（允许信号）；0=趋势偏弱（可过滤信号）
    out["regime_ok"] = (out["ma_short"] >= out["ma_long"]).astype(int)
    return out
