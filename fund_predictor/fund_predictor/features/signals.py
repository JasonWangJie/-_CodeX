import numpy as np
import pandas as pd


def add_signals(df: pd.DataFrame, r1_floor: float, r2_floor: float, cfg: dict) -> pd.DataFrame:
    out = df.copy()
    accel_min = cfg["feature"]["accel_min"]

    r1_th = np.maximum(out["r1_q"], r1_floor)
    r2_th = np.maximum(out["r2_q"], r2_floor)

    r1_valid = out["R1"] >= r1_th
    r2_valid = out["R2"] >= r2_th
    accel_valid = out["accel"] >= accel_min

    out["signal"] = (r1_valid | r2_valid) & accel_valid

    r1_score = out["R1"] / r1_th
    r2_score = out["R2"] / r2_th
    accel_score = np.minimum(out["accel"] / accel_min, 2.0)
    out["signal_intensity"] = np.maximum(r1_score, r2_score) * 0.7 + accel_score * 0.3
    out["signal_intensity"] = out["signal_intensity"].replace([np.inf, -np.inf], np.nan).fillna(0)
    return out
