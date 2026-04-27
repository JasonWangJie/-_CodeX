import numpy as np
import pandas as pd


def add_signals(df: pd.DataFrame, r1_floor: float, r2_floor: float, cfg: dict) -> pd.DataFrame:
    out = df.copy()
    accel_min = cfg["feature"]["accel_min"]
    enh = cfg.get("enhancement", {})

    r1_th = np.maximum(out["r1_q"], r1_floor)
    r2_th = np.maximum(out["r2_q"], r2_floor)

    r1_valid = out["R1"] >= r1_th
    r2_valid = out["R2"] >= r2_th
    accel_valid = out["accel"] >= accel_min

    raw_signal = (r1_valid | r2_valid) & accel_valid

    r1_score = out["R1"] / r1_th
    r2_score = out["R2"] / r2_th
    accel_score = np.minimum(out["accel"] / accel_min, 2.0)
    out["signal_intensity"] = np.maximum(r1_score, r2_score) * 0.7 + accel_score * 0.3
    out["signal_intensity"] = out["signal_intensity"].replace([np.inf, -np.inf], np.nan).fillna(0)

    # 信号强度分层：用于后续统计不同层级信号质量。
    if enh.get("enable_intensity_layer", True):
        strong_th = float(enh.get("strong_threshold", 1.6))
        out["intensity_level"] = np.select(
            [
                out["signal_intensity"] >= strong_th,
                out["signal_intensity"] >= 1.2,
                out["signal_intensity"] >= 1.0,
            ],
            ["strong", "medium", "weak"],
            default="none",
        )
    else:
        out["intensity_level"] = "none"

    # 趋势过滤：趋势偏弱时可屏蔽信号，减少逆势抄底噪声。
    if enh.get("enable_regime_filter", True) and "regime_ok" in out.columns:
        out["signal"] = raw_signal & (out["regime_ok"] == 1)
    else:
        out["signal"] = raw_signal
    return out
