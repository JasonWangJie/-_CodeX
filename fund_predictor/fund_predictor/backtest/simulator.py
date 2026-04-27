import pandas as pd


def simulate_trades(df: pd.DataFrame, m: int, n: int, cfg: dict) -> pd.DataFrame:
    price = df["price"].reset_index(drop=True)
    dates = pd.to_datetime(df["nav_date"]).reset_index(drop=True)
    hv = df["HV90"].reset_index(drop=True)
    intensity = df["signal_intensity"].reset_index(drop=True)
    signal_idx = df.index[df["signal"]].tolist()

    rows = []
    # 交易成本与滑点采用“单边费率”建模：
    # 买入价上调（更贵），卖出价下调（更低），使回测更贴近真实执行。
    cost_rate = float(cfg["strategy"].get("transaction_cost_rate", 0.0))
    slippage_rate = float(cfg["strategy"].get("slippage_rate", 0.0))
    buy_adjust = 1 + cost_rate + slippage_rate
    sell_adjust = 1 - cost_rate - slippage_rate

    for idx in signal_idx:
        buy_idx = idx + m
        if buy_idx >= len(df):
            continue
        maturity_idx = min(buy_idx + n, len(df) - 1)
        threshold = cfg["strategy"]["take_profit_hv_multiplier"] * (hv.iloc[buy_idx] if pd.notna(hv.iloc[buy_idx]) else 0)
        confirm_days = cfg["strategy"]["take_profit_confirm_days"]

        consec = 0
        sell_idx = maturity_idx
        reason = "maturity"
        for j in range(buy_idx, maturity_idx + 1):
            floating_return = price.iloc[j] / price.iloc[buy_idx] - 1
            if floating_return > threshold:
                consec += 1
            else:
                consec = 0
            if consec >= confirm_days:
                sell_idx = j
                reason = "take_profit"
                break

        raw_buy_price = price.iloc[buy_idx]
        raw_sell_price = price.iloc[sell_idx]
        exec_buy_price = raw_buy_price * buy_adjust
        exec_sell_price = raw_sell_price * sell_adjust

        rows.append(
            {
                "signal_date": dates.iloc[idx],
                "buy_date": dates.iloc[buy_idx],
                "sell_date": dates.iloc[sell_idx],
                "buy_price": exec_buy_price,
                "sell_price": exec_sell_price,
                "return": exec_sell_price / exec_buy_price - 1,
                "exit_reason": reason,
                "m": m,
                "n": n,
                "hv": hv.iloc[buy_idx],
                "signal_intensity": intensity.iloc[idx],
                "intensity_level": df.iloc[idx].get("intensity_level", "none"),
            }
        )
    return pd.DataFrame(rows)
