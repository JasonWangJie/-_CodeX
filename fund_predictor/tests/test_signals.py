import pytest

pd = pytest.importorskip("pandas")


from fund_predictor.features.signals import add_signals


def _base_cfg():
    return {
        "feature": {"accel_min": 1.0},
        "enhancement": {
            "enable_intensity_layer": True,
            "enable_regime_filter": True,
            "enable_probability_fusion": True,
            "enable_low_confidence_filter": False,
            "support_target": 2,
            "strong_threshold": 1.6,
        },
    }


def _sample_df():
    return pd.DataFrame(
        {
            "r1_q": [1.0, 1.0, 1.0, 1.0],
            "r2_q": [1.0, 1.0, 1.0, 1.0],
            "R1": [1.1, 1.2, 1.3, 1.4],
            "R2": [0.9, 1.1, 1.2, 1.3],
            "accel": [1.0, 1.1, 1.2, 1.3],
            "regime_ok": [1, 1, 1, 1],
        }
    )


def test_probability_fusion_outputs_are_present_and_bounded():
    out = add_signals(_sample_df(), r1_floor=1.0, r2_floor=1.0, cfg=_base_cfg())

    assert {"prob_reg", "prob_cls", "prob_fused", "prob_weight_cls"}.issubset(out.columns)
    assert out["prob_reg"].between(0, 1).all()
    assert out["prob_cls"].between(0, 1).all()
    assert out["prob_fused"].between(0, 1).all()
    assert out["prob_weight_cls"].between(0, 1).all()
    assert out["prob_weight_cls"].is_monotonic_increasing


def test_low_confidence_filter_can_block_signals():
    cfg = _base_cfg()
    cfg["enhancement"]["enable_low_confidence_filter"] = True
    cfg["enhancement"]["min_signal_prob"] = 0.99

    baseline_cfg = _base_cfg()
    baseline = add_signals(_sample_df(), r1_floor=1.0, r2_floor=1.0, cfg=baseline_cfg)
    filtered = add_signals(_sample_df(), r1_floor=1.0, r2_floor=1.0, cfg=cfg)

    assert baseline["signal"].sum() > 0
    assert filtered["signal"].sum() < baseline["signal"].sum()
