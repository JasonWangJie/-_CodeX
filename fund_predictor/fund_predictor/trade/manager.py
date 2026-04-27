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
        return {"positions": {}, "orders": [], "realized_pnl": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    # 兼容旧版本账本文件：补齐新增字段。
    data.setdefault("positions", {})
    data.setdefault("orders", [])
    data.setdefault("realized_pnl", [])
    return data


def save_portfolio(meta_dir: str, data: dict[str, Any]) -> None:
    """保存持仓账本到本地 JSON 文件。"""
    path = _portfolio_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def init_portfolio_db(meta_dir: str, reset: bool = False) -> str:
    """
    初始化本地交易数据库文件。
    - reset=False: 若已存在则保留，不覆盖历史。
    - reset=True: 强制重置为空账本（会清空历史记录）。
    """
    path = _portfolio_path(meta_dir)
    if path.exists() and not reset:
        return f"数据库已存在：{path}"
    save_portfolio(meta_dir, {"positions": {}, "orders": [], "realized_pnl": []})
    return f"数据库初始化成功：{path}"


def buy_fund(meta_dir: str, fund_code: str, fund_name: str, shares: float, price: float, trade_date: str | None, note: str) -> dict[str, Any]:
    """
    买入基金并更新持仓。
    - 使用加权平均法更新持仓成本。
    - 同时记录一条订单流水，便于复盘。
    """
    if shares <= 0 or price <= 0:
        raise ValueError("买入份额与买入价格必须大于 0")

    data = load_portfolio(meta_dir)
    if "realized_pnl" not in data:
        data["realized_pnl"] = []
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
    if "realized_pnl" not in data:
        data["realized_pnl"] = []
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
    if "realized_pnl" not in data:
        data["realized_pnl"] = []
    pos = data["positions"].get(fund_code)
    if not pos:
        raise ValueError(f"基金 {fund_code} 当前无持仓，无法卖出")

    current_shares = float(pos.get("shares", 0.0))
    avg_cost = float(pos.get("avg_cost", 0.0))
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
            "cost_basis": avg_cost,
            "realized_return": (price / avg_cost - 1) if avg_cost > 0 else None,
            "realized_pnl": (price - avg_cost) * shares,
            "trade_date": trade_date or _today_str(),
            "note": note,
        }
    )
    data["realized_pnl"].append(
        {
            "fund_code": fund_code,
            "fund_name": pos.get("fund_name", "未知基金名称"),
            "trade_date": trade_date or _today_str(),
            "shares": shares,
            "sell_price": price,
            "cost_basis": avg_cost,
            "realized_return": (price / avg_cost - 1) if avg_cost > 0 else None,
            "realized_pnl": (price - avg_cost) * shares,
            "order_type": order_type,
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


def get_profit_summary(meta_dir: str, latest_prices: dict[str, float] | None = None) -> dict[str, Any]:
    """
    计算收益概览：
    1) 已实现收益：仅统计历史卖出记录（卖出后不再继续累积）。
    2) 未实现收益：仅统计当前仍持仓基金。
    """
    latest_prices = latest_prices or {}
    data = load_portfolio(meta_dir)
    positions = data.get("positions", {})
    realized_list = data.get("realized_pnl", [])

    realized_total = float(sum(float(x.get("realized_pnl", 0.0)) for x in realized_list))
    realized_count = len(realized_list)

    unrealized_total = 0.0
    unrealized_details = []
    for fund_code, pos in positions.items():
        if fund_code not in latest_prices:
            # 没有最新价格时只返回仓位基础信息，不参与未实现收益计算。
            unrealized_details.append(
                {
                    "fund_code": fund_code,
                    "fund_name": pos.get("fund_name", "未知基金名称"),
                    "shares": pos.get("shares", 0.0),
                    "avg_cost": pos.get("avg_cost", 0.0),
                    "latest_price": None,
                    "unrealized_pnl": None,
                    "unrealized_return": None,
                }
            )
            continue

        latest_price = float(latest_prices[fund_code])
        shares = float(pos.get("shares", 0.0))
        avg_cost = float(pos.get("avg_cost", 0.0))
        pnl = (latest_price - avg_cost) * shares
        ret = (latest_price / avg_cost - 1) if avg_cost > 0 else None
        unrealized_total += pnl
        unrealized_details.append(
            {
                "fund_code": fund_code,
                "fund_name": pos.get("fund_name", "未知基金名称"),
                "shares": shares,
                "avg_cost": avg_cost,
                "latest_price": latest_price,
                "unrealized_pnl": pnl,
                "unrealized_return": ret,
            }
        )

    return {
        "realized_total": realized_total,
        "realized_count": realized_count,
        "unrealized_total": unrealized_total,
        "total_pnl": realized_total + unrealized_total,
        "realized_details": realized_list,
        "unrealized_details": unrealized_details,
    }


def undo_last_order(meta_dir: str) -> dict[str, Any]:
    """
    撤销最近一笔订单（仅本地账本层面）。
    支持撤销类型：buy / sell / partial_sell / track。
    """
    data = load_portfolio(meta_dir)
    orders = data.get("orders", [])
    if not orders:
        raise ValueError("暂无可撤销的订单")

    last = orders.pop()
    order_type = last.get("type")
    code = str(last.get("fund_code", ""))
    pos = data.get("positions", {}).get(code)

    if order_type == "buy":
        # 撤销买入：从当前持仓扣回本次买入份额，并按剩余成本回退。
        if not pos:
            raise ValueError("撤销失败：当前无该基金持仓，无法回退买入")
        buy_shares = float(last.get("shares", 0.0))
        buy_price = float(last.get("price", 0.0))
        cur_shares = float(pos.get("shares", 0.0))
        cur_avg = float(pos.get("avg_cost", 0.0))
        if buy_shares > cur_shares:
            raise ValueError("撤销失败：当前持仓份额小于待撤销买入份额")
        remain = cur_shares - buy_shares
        if remain <= 0:
            data["positions"].pop(code, None)
        else:
            # 由加权平均公式反推剩余成本。
            remain_cost = (cur_shares * cur_avg - buy_shares * buy_price) / remain
            pos["shares"] = round(remain, 6)
            pos["avg_cost"] = round(remain_cost, 6)
            pos["updated_at"] = datetime.utcnow().isoformat()

    elif order_type in {"sell", "partial_sell"}:
        # 撤销卖出：把卖出的份额加回持仓，并恢复成本（卖出不改变成本）。
        sell_shares = float(last.get("shares", 0.0))
        cost_basis = float(last.get("cost_basis", 0.0))
        if not pos:
            data["positions"][code] = {
                "fund_code": code,
                "fund_name": last.get("fund_name", "未知基金名称"),
                "shares": round(sell_shares, 6),
                "avg_cost": round(cost_basis, 6),
                "take_profit": None,
                "stop_loss": None,
                "notes": "",
                "updated_at": datetime.utcnow().isoformat(),
            }
        else:
            pos["shares"] = round(float(pos.get("shares", 0.0)) + sell_shares, 6)
            pos["avg_cost"] = round(cost_basis if cost_basis > 0 else float(pos.get("avg_cost", 0.0)), 6)
            pos["updated_at"] = datetime.utcnow().isoformat()

        # 同步撤销已实现收益记录（若最后一条对应此订单则删除）。
        realized = data.get("realized_pnl", [])
        if realized:
            tail = realized[-1]
            if (
                str(tail.get("fund_code", "")) == code
                and float(tail.get("shares", 0.0)) == sell_shares
                and str(tail.get("order_type", "")) == order_type
            ):
                realized.pop()

    elif order_type == "track":
        # 撤销跟踪：当前版本不保存 track 前快照，因此仅删除流水并给出提示。
        pass
    else:
        raise ValueError(f"不支持撤销的订单类型：{order_type}")

    save_portfolio(meta_dir, data)
    return {"undone_order": last, "message": "撤销成功"}
