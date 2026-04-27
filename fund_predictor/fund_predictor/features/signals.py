import numpy as np
import pandas as pd


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


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

    # 双通道概率融合（轻量实现，无需额外ML框架）：
    # 1) prob_reg：由信号强度经sigmoid校准得到“回归通道概率”
    # 2) prob_cls：由规则特征组合经sigmoid得到“直接分类通道概率”
    # 3) 按样本支持度动态融合权重。
    if enh.get("enable_probability_fusion", True):
        prob_reg = _sigmoid((out["signal_intensity"] - 1.0) * 2.0)
        cls_score = (
            (out["R1"].fillna(0) / (r1_floor if r1_floor > 0 else 1.0)) * 0.4
            + (out["R2"].fillna(0) / (r2_floor if r2_floor > 0 else 1.0)) * 0.4
            + (out["accel"].fillna(0) / (cfg["feature"]["accel_min"] if cfg["feature"]["accel_min"] > 0 else 1.0)) * 0.2
        )
        prob_cls = _sigmoid((cls_score - 1.0) * 1.5)

        support_target = float(enh.get("support_target", 50))
        # 样本支持度：按历史信号累计数量构建，越靠后支持度越高。
        support = out["signal"].fillna(False).astype(int).shift(1).fillna(0).cumsum()
        weight_cls = np.clip(support / support_target, 0.0, 1.0)
        out["prob_reg"] = prob_reg
        out["prob_cls"] = prob_cls
        out["prob_fused"] = prob_reg * (1.0 - weight_cls) + prob_cls * weight_cls
        out["prob_weight_cls"] = weight_cls

        # 低置信度过滤与放行机制。
        if enh.get("enable_low_confidence_filter", True):
            min_prob = float(enh.get("min_signal_prob", 0.55))
            out["signal"] = out["signal"] & (out["prob_fused"] >= min_prob)
    else:
        out["prob_reg"] = np.nan
        out["prob_cls"] = np.nan
        out["prob_fused"] = np.nan
        out["prob_weight_cls"] = np.nan
    return out
