import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _today_str() -> str:
    """返回当天日期字符串（YYYY-MM-DD）。"""
    return datetime.utcnow().strftime("%Y-%m-%d")


def _portfolio_path(meta_dir: str) -> Path:
    """统一定义持仓文件路径，避免各处硬编码。"""
    return Path(meta_dir) / "portfolio.json"


def load_portfolio(meta_dir: str) -> dict[str, Any]:
    """
    读取持仓账本。
    若文件不存在则返回默认空结构，保证首次使用也能正常工作。
    """
    path = _portfolio_path(meta_dir)
    if not path.exists():
        return {"positions": {}, "orders": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_portfolio(meta_dir: str, data: dict[str, Any]) -> None:
    """保存持仓账本到本地 JSON 文件。"""
    path = _portfolio_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def buy_fund(meta_dir: str, fund_code: str, fund_name: str, shares: float, price: float, trade_date: str | None, note: str) -> dict[str, Any]:
    """
    买入基金并更新持仓。
    - 使用加权平均法更新持仓成本。
    - 同时记录一条订单流水，便于复盘。
    """
    if shares <= 0 or price <= 0:
        raise ValueError("买入份额与买入价格必须大于 0")

    data = load_portfolio(meta_dir)
    positions = data["positions"]
    key = fund_code
    date_value = trade_date or _today_str()

    old = positions.get(key, {"fund_code": fund_code, "fund_name": fund_name, "shares": 0.0, "avg_cost": 0.0, "notes": ""})
    old_shares = float(old.get("shares", 0.0))
    old_cost = float(old.get("avg_cost", 0.0))
    new_total_shares = old_shares + shares
    new_avg_cost = ((old_shares * old_cost) + (shares * price)) / new_total_shares

    positions[key] = {
        "fund_code": fund_code,
        "fund_name": fund_name or old.get("fund_name", "未知基金名称"),
        "shares": round(new_total_shares, 6),
        "avg_cost": round(new_avg_cost, 6),
        "take_profit": old.get("take_profit"),
        "stop_loss": old.get("stop_loss"),
        "notes": note or old.get("notes", ""),
        "updated_at": datetime.utcnow().isoformat(),
    }

    data["orders"].append(
        {
            "type": "buy",
            "fund_code": fund_code,
            "fund_name": positions[key]["fund_name"],
            "shares": shares,
            "price": price,
            "trade_date": date_value,
            "note": note,
        }
    )
    save_portfolio(meta_dir, data)
    return positions[key]


def track_fund(meta_dir: str, fund_code: str, note: str | None, take_profit: float | None, stop_loss: float | None) -> dict[str, Any]:
    """
    更新跟踪信息（备注、止盈、止损）。
    该命令不改变持仓份额，仅维护跟踪参数。
    """
    data = load_portfolio(meta_dir)
    pos = data["positions"].get(fund_code)
    if not pos:
        raise ValueError(f"基金 {fund_code} 当前无持仓，无法跟踪")

    if note is not None:
        pos["notes"] = note
    if take_profit is not None:
        pos["take_profit"] = take_profit
    if stop_loss is not None:
        pos["stop_loss"] = stop_loss
    pos["updated_at"] = datetime.utcnow().isoformat()

    data["orders"].append(
        {
            "type": "track",
            "fund_code": fund_code,
            "fund_name": pos.get("fund_name", "未知基金名称"),
            "trade_date": _today_str(),
            "note": note,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
        }
    )
    save_portfolio(meta_dir, data)
    return pos


def sell_fund(meta_dir: str, fund_code: str, shares: float, price: float, trade_date: str | None, note: str, order_type: str = "sell") -> dict[str, Any]:
    """
    卖出/部分卖出基金。
    - 当卖出份额等于当前持仓时，自动清仓。
    - 当卖出份额小于持仓时，自动保留剩余持仓。
    """
    if shares <= 0 or price <= 0:
        raise ValueError("卖出份额与卖出价格必须大于 0")

    data = load_portfolio(meta_dir)
    pos = data["positions"].get(fund_code)
    if not pos:
        raise ValueError(f"基金 {fund_code} 当前无持仓，无法卖出")

    current_shares = float(pos.get("shares", 0.0))
    if shares > current_shares:
        raise ValueError(f"卖出份额 {shares} 超过当前持仓 {current_shares}")

    remain = round(current_shares - shares, 6)
    if remain <= 0:
        data["positions"].pop(fund_code, None)
        after_state = {"fund_code": fund_code, "shares": 0.0, "status": "已清仓"}
    else:
        pos["shares"] = remain
        pos["updated_at"] = datetime.utcnow().isoformat()
        after_state = pos

    data["orders"].append(
        {
            "type": order_type,
            "fund_code": fund_code,
            "fund_name": pos.get("fund_name", "未知基金名称"),
            "shares": shares,
            "price": price,
            "trade_date": trade_date or _today_str(),
            "note": note,
        }
    )
    save_portfolio(meta_dir, data)
    return after_state


def list_positions(meta_dir: str) -> list[dict[str, Any]]:
    """返回当前持仓列表。"""
    data = load_portfolio(meta_dir)
    return list(data.get("positions", {}).values())


def list_orders(meta_dir: str, limit: int = 20) -> list[dict[str, Any]]:
    """返回最近 N 条订单流水。"""
    data = load_portfolio(meta_dir)
    orders = data.get("orders", [])
    return orders[-limit:]
