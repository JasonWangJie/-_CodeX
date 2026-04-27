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
    return out
