import argparse
import json
from pathlib import Path

from fund_predictor.backtest.grid_search import run_grid_search
from fund_predictor.backtest.walk_forward import append_tuning_history, run_walk_forward
from fund_predictor.config import load_config
from fund_predictor.data.fetcher import fetch_and_update_fund
from fund_predictor.data.storage import load_nav
from fund_predictor.features.indicators import add_indicators
from fund_predictor.report.renderer import render_reports
from fund_predictor.trade.manager import (
    buy_fund,
    get_profit_summary,
    init_portfolio_db,
    list_orders,
    list_positions,
    sell_fund,
    track_fund,
    undo_last_order,
)
from fund_predictor.utils.logger import setup_logger
from fund_predictor.utils.time_utils import now_str

状态中文映射 = {
    "success": "成功",
    "fetch_failed": "抓取失败",
    "parse_failed": "解析失败",
    "insufficient_data": "样本不足",
}


def _load_funds(args) -> list[str]:
    """
    汇总基金代码来源（优先级从高到低）：
    1) --funds 命令行输入
    2) --fund-file 文本文件
    3) config.yaml 指定的 JSON 文件（runtime.funds_json）
    """
    funds = list(args.funds or [])
    if args.fund_file:
        txt = Path(args.fund_file).read_text(encoding="utf-8")
        funds.extend([x.strip() for x in txt.splitlines() if x.strip()])

    # 命令行没有传基金时，自动回落到配置 JSON。
    if not funds:
        cfg = load_config(args.config)
        funds_json = cfg.get("runtime", {}).get("funds_json", "")
        if funds_json:
            path = Path(funds_json)
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                # 支持两种格式：
                # 1) ["009689", "005827"]
                # 2) [{"fund_code":"009689","fund_name":"xxx"}, ...]
                if isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, str):
                            funds.append(item.strip())
                        elif isinstance(item, dict) and item.get("fund_code"):
                            funds.append(str(item["fund_code"]).strip())
    return funds


def _persist_status(meta_dir: str, statuses: list[dict]) -> None:
    """将基金抓取状态落盘，供报告和后续审计使用。"""
    Path(meta_dir).mkdir(parents=True, exist_ok=True)
    (Path(meta_dir) / "fetch_status.json").write_text(json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze(args):
    """一体化流程：更新数据 -> 计算特征 -> 网格回测 -> 生成报告。"""
    cfg = load_config(args.config)
    logger = setup_logger("output/logs", cfg["runtime"].get("log_level", "INFO"))
    funds = _load_funds(args)[: cfg["runtime"]["max_funds_per_run"]]

    statuses = []
    ranking = []
    wf_records = []
    for fund_code in funds:
        df, status = fetch_and_update_fund(fund_code, cfg, logger)
        statuses.append(status.__dict__)
        if not status.used_in_analysis or df.empty or len(df) < 260:
            statuses[-1]["status"] = "insufficient_data" if df.empty or len(df) < 260 else statuses[-1]["status"]
            statuses[-1]["used_in_analysis"] = False
            statuses[-1]["status_cn"] = 状态中文映射.get(statuses[-1]["status"], statuses[-1]["status"])
            continue
        statuses[-1]["status_cn"] = 状态中文映射.get(statuses[-1]["status"], statuses[-1]["status"])

        # 先计算技术指标，再进入参数搜索与回测。
        idf = add_indicators(df, cfg)
        best = run_grid_search(idf, cfg)
        if not best:
            statuses[-1]["status"] = "insufficient_data"
            statuses[-1]["used_in_analysis"] = False
            continue

        latest = best["signal_df"].iloc[-1]
        fund_name = ""
        if "fund_name" in idf.columns and not idf["fund_name"].dropna().empty:
            fund_name = str(idf["fund_name"].dropna().iloc[-1]).strip()
        ranking.append(
            {
                "fund_code": fund_code,
                "fund_name": fund_name or status.fund_name or "未知基金名称",
                "score": best["score"],
                "m": best["m"],
                "n": best["n"],
                "metrics": best["metrics"],
                "signal_intensity": float(latest["signal_intensity"]),
                "trades": best["trades"],
            }
        )
        wf = run_walk_forward(idf, cfg, fund_code)
        wf_records.extend(wf)

    append_tuning_history(wf_records, cfg["storage"]["meta_dir"])
    _persist_status(cfg["storage"]["meta_dir"], statuses)

    ranking = sorted(ranking, key=lambda x: x["score"], reverse=True)
    stamp = now_str()
    context = {
        "summary": {
            "run_time": stamp,
            "total_funds": len(funds),
            "success_count": len(ranking),
            "failed_count": len(funds) - len(ranking),
        },
        "statuses": statuses,
        "ranking": ranking,
    }
    paths = render_reports(context, cfg["storage"]["output_dir"], stamp)
    logger.info("报告已生成：%s", paths)
    return 0


def update_data(args):
    """仅执行数据更新，不进入回测和报告阶段。"""
    cfg = load_config(args.config)
    logger = setup_logger("output/logs", cfg["runtime"].get("log_level", "INFO"))
    funds = _load_funds(args)
    for fund_code in funds:
        fetch_and_update_fund(fund_code, cfg, logger)
    return 0


def backtest_only(args):
    """复用 analyze 主流程，当前版本与 analyze 行为一致。"""
    return analyze(args)


def report_latest(args):
    """输出最近一次生成的 Markdown 报告路径。"""
    out = Path("output/reports")
    reports = sorted(out.glob("report_*.md"))
    if not reports:
        print("未找到历史报告文件")
        return 1
    print(f"最新报告：{reports[-1]}")
    return 0


def buy_cmd(args):
    """买入命令：用于登记建仓或加仓。"""
    cfg = load_config(args.config)
    pos = buy_fund(
        meta_dir=cfg["storage"]["meta_dir"],
        fund_code=args.fund_code,
        fund_name=args.fund_name or "未知基金名称",
        shares=args.shares,
        price=args.price,
        trade_date=args.trade_date,
        note=args.note or "",
    )
    print(
        f"买入记录成功：基金代码={pos['fund_code']}，基金名称={pos['fund_name']}，"
        f"当前份额={pos['shares']}，持仓成本={pos['avg_cost']}"
    )
    return 0


def track_cmd(args):
    """跟踪命令：更新止盈止损及备注，不改动份额。"""
    cfg = load_config(args.config)
    pos = track_fund(
        meta_dir=cfg["storage"]["meta_dir"],
        fund_code=args.fund_code,
        note=args.note,
        take_profit=args.take_profit,
        stop_loss=args.stop_loss,
    )
    print(
        f"跟踪信息已更新：基金代码={pos['fund_code']}，基金名称={pos.get('fund_name', '未知基金名称')}，"
        f"止盈={pos.get('take_profit')}，止损={pos.get('stop_loss')}，备注={pos.get('notes', '')}"
    )
    return 0


def sell_cmd(args):
    """卖出命令：用于全卖或按份额卖出。"""
    cfg = load_config(args.config)
    if not getattr(args, "yes", False):
        confirm = input(
            f"确认卖出？基金代码={args.fund_code}，份额={args.shares}，价格={args.price}。输入 yes 确认："
        ).strip().lower()
        if confirm != "yes":
            print("已取消卖出操作。")
            return 0
    after = sell_fund(
        meta_dir=cfg["storage"]["meta_dir"],
        fund_code=args.fund_code,
        shares=args.shares,
        price=args.price,
        trade_date=args.trade_date,
        note=args.note or "",
        order_type="sell",
    )
    print(f"卖出完成：基金代码={args.fund_code}，卖出份额={args.shares}，卖出价格={args.price}，卖后状态={after}")
    return 0


def partial_sell_cmd(args):
    """部分卖出命令：语义上更明确，底层与卖出逻辑复用。"""
    cfg = load_config(args.config)
    if not getattr(args, "yes", False):
        confirm = input(
            f"确认部分卖出？基金代码={args.fund_code}，份额={args.shares}，价格={args.price}。输入 yes 确认："
        ).strip().lower()
        if confirm != "yes":
            print("已取消部分卖出操作。")
            return 0
    after = sell_fund(
        meta_dir=cfg["storage"]["meta_dir"],
        fund_code=args.fund_code,
        shares=args.shares,
        price=args.price,
        trade_date=args.trade_date,
        note=args.note or "",
        order_type="partial_sell",
    )
    print(f"部分卖出完成：基金代码={args.fund_code}，卖出份额={args.shares}，卖后状态={after}")
    return 0


def positions_cmd(args):
    """查看当前持仓。"""
    cfg = load_config(args.config)
    positions = list_positions(cfg["storage"]["meta_dir"])
    if not positions:
        print("当前暂无持仓记录")
        return 0
    print("当前持仓列表：")
    for item in positions:
        print(
            f"- 基金代码={item.get('fund_code')}，基金名称={item.get('fund_name')}，"
            f"份额={item.get('shares')}，持仓成本={item.get('avg_cost')}，"
            f"止盈={item.get('take_profit')}，止损={item.get('stop_loss')}，备注={item.get('notes', '')}"
        )
    return 0


def history_cmd(args):
    """查看交易流水历史。"""
    cfg = load_config(args.config)
    orders = list_orders(cfg["storage"]["meta_dir"], args.limit)
    if not orders:
        print("暂无交易流水")
        return 0
    print(f"最近 {len(orders)} 条交易流水：")
    for item in orders:
        print(item)
    return 0


def undo_last_cmd(args):
    """撤销最近一笔订单。"""
    cfg = load_config(args.config)
    if not getattr(args, "yes", False):
        confirm = input("确认撤销最近一笔订单？输入 yes 确认：").strip().lower()
        if confirm != "yes":
            print("已取消撤销操作。")
            return 0
    result = undo_last_order(cfg["storage"]["meta_dir"])
    print("撤销结果：", result)
    return 0


def init_db_cmd(args):
    """初始化或重置本地交易数据库。"""
    cfg = load_config(args.config)
    # reset 场景属于高风险动作，默认二次确认，避免误清空历史数据。
    if getattr(args, "reset", False) and not getattr(args, "yes", False):
        confirm = input("你正在执行重置数据库操作，历史记录将被清空。输入 yes 确认：").strip().lower()
        if confirm != "yes":
            print("已取消重置操作。")
            return 0
    msg = init_portfolio_db(cfg["storage"]["meta_dir"], reset=args.reset)
    print(msg)
    return 0


def _build_latest_price_map(cfg: dict, positions: list[dict]) -> dict[str, float]:
    """
    从本地净值缓存中读取各持仓基金最新净值，作为未实现收益计算输入。
    价格优先级：acc_nav > unit_nav。
    """
    price_map: dict[str, float] = {}
    nav_dir = cfg["storage"]["nav_dir"]
    fmt = cfg["storage"]["file_format"]
    for pos in positions:
        code = pos.get("fund_code")
        if not code:
            continue
        df = load_nav(nav_dir, str(code), fmt)
        if df.empty:
            continue
        row = df.sort_values("nav_date").iloc[-1]
        acc = row.get("acc_nav")
        unit = row.get("unit_nav")
        price = acc if acc is not None else unit
        if price is None:
            continue
        try:
            price_map[str(code)] = float(price)
        except (TypeError, ValueError):
            continue
    return price_map


def profit_summary_cmd(args):
    """查询收益明细与收益概览（已实现 + 未实现）。"""
    cfg = load_config(args.config)
    positions = list_positions(cfg["storage"]["meta_dir"])
    latest_price_map = _build_latest_price_map(cfg, positions)
    summary = get_profit_summary(cfg["storage"]["meta_dir"], latest_prices=latest_price_map)

    print("收益概览：")
    print(f"- 已实现收益合计：{summary['realized_total']:.6f}")
    print(f"- 未实现收益合计：{summary['unrealized_total']:.6f}")
    print(f"- 总收益（已实现+未实现）：{summary['total_pnl']:.6f}")
    print(f"- 历史卖出记录数：{summary['realized_count']}")

    def _render_table(title: str, columns: list[str], rows: list[dict]) -> None:
        """
        终端文本表格渲染器：
        - 无需额外依赖（如 tabulate）；
        - 统一字段顺序，提升可读性。
        """
        print(f"\n{title}")
        if not rows:
            print("（无数据）")
            return
        widths = {col: max(len(col), *(len(str(r.get(col, ""))) for r in rows)) for col in columns}
        header = " | ".join(col.ljust(widths[col]) for col in columns)
        sep = "-+-".join("-" * widths[col] for col in columns)
        print(header)
        print(sep)
        for row in rows:
            print(" | ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns))

    _render_table(
        "未实现收益明细（当前持仓）",
        ["fund_code", "fund_name", "shares", "avg_cost", "latest_price", "unrealized_pnl", "unrealized_return"],
        summary["unrealized_details"],
    )
    _render_table(
        "已实现收益明细（历史卖出）",
        ["fund_code", "fund_name", "trade_date", "shares", "sell_price", "cost_basis", "realized_pnl", "realized_return", "order_type"],
        summary["realized_details"],
    )
    return 0


def console_cmd(args):
    """
    交互控制台应用：
    1 整体跑一遍 2 跟踪 3 买入 4 卖出 5 部分卖出 6 初始化数据库 7 查询收益 8 撤销最近订单 0 退出
    1 整体跑一遍 2 跟踪 3 买入 4 卖出 5 部分卖出 6 初始化数据库 7 查询收益 0 退出
    """
    # 在交互控制台中记录“最近使用基金代码”，用于减少重复输入成本。
    last_fund_code = ""

    def _input_with_default(prompt: str, default_value: str = "") -> str:
        """支持回车复用默认值的输入函数。"""
        if default_value:
            text = input(f"{prompt}（回车沿用 {default_value}）：").strip()
            return text or default_value
        return input(f"{prompt}：").strip()

    def _input_float(prompt: str, default_value: float | None = None) -> float:
        """带重试的浮点数输入，避免一次输错导致流程中断。"""
        while True:
            if default_value is None:
                raw = input(f"{prompt}：").strip()
            else:
                raw = input(f"{prompt}（回车沿用 {default_value}）：").strip() or str(default_value)
            try:
                return float(raw)
            except ValueError:
                print("输入格式错误，请输入数字。")

    while True:
        print("\n=== 基金控制台 ===")
        print("1. 整体跑一遍（analyze）")
        print("2. 跟踪（track）")
        print("3. 买入（buy）")
        print("4. 卖出（sell）")
        print("5. 部分卖出（partial-sell）")
        print("6. 初始化数据库（init-db）")
        print("7. 查询收益（profit-summary）")
        print("8. 撤销最近订单（undo-last）")
        print("0. 退出")
        choice = input("请输入菜单编号：").strip()

        if choice == "0":
            print("已退出控制台。")
            return 0
        if choice == "1":
            funds_text = input("请输入基金代码（空格分隔）：").strip()
            # 交互输入为空时，会自动回落到配置 JSON 基金池。
            args.funds = [x for x in funds_text.split() if x]
            analyze(args)
            continue
        if choice == "2":
            args.fund_code = _input_with_default("请输入基金代码", last_fund_code)
            last_fund_code = args.fund_code
            tp = input("请输入止盈阈值（可留空）：").strip()
            sl = input("请输入止损阈值（可留空）：").strip()
            args.take_profit = float(tp) if tp else None
            args.stop_loss = float(sl) if sl else None
            args.note = input("请输入跟踪备注（可留空）：").strip() or None
            track_cmd(args)
            continue
        if choice == "3":
            args.fund_code = _input_with_default("请输入基金代码", last_fund_code)
            last_fund_code = args.fund_code
            args.fund_name = input("请输入基金名称（可留空）：").strip()
            args.trade_date = input("请输入买入日期（YYYY-MM-DD，可留空默认当天）：").strip() or None
            args.price = _input_float("请输入买入净值")
            args.shares = _input_float("请输入买入份额")
            args.price = float(input("请输入买入净值：").strip())
            args.shares = float(input("请输入买入份额：").strip())
            args.note = input("请输入备注（可留空）：").strip() or None
            buy_cmd(args)
            continue
        if choice == "4":
            args.fund_code = _input_with_default("请输入基金代码", last_fund_code)
            last_fund_code = args.fund_code
            args.trade_date = input("请输入卖出日期（YYYY-MM-DD，可留空默认当天）：").strip() or None
            args.price = _input_float("请输入卖出净值")
            args.shares = _input_float("请输入卖出份额")
            args.price = float(input("请输入卖出净值：").strip())
            args.shares = float(input("请输入卖出份额：").strip())
            args.note = input("请输入备注（可留空）：").strip() or None
            args.yes = True
            sell_cmd(args)
            continue
        if choice == "5":
            args.fund_code = _input_with_default("请输入基金代码", last_fund_code)
            last_fund_code = args.fund_code
            args.trade_date = input("请输入卖出日期（YYYY-MM-DD，可留空默认当天）：").strip() or None
            args.price = _input_float("请输入部分卖出净值")
            args.shares = _input_float("请输入部分卖出份额")
            args.price = float(input("请输入部分卖出净值：").strip())
            args.shares = float(input("请输入部分卖出份额：").strip())
            args.note = input("请输入备注（可留空）：").strip() or None
            args.yes = True
            partial_sell_cmd(args)
            continue
        if choice == "6":
            reset = input("是否重置已有数据库？输入 yes 表示重置：").strip().lower() == "yes"
            args.reset = reset
            args.yes = True
            init_db_cmd(args)
            continue
        if choice == "7":
            profit_summary_cmd(args)
            continue
        if choice == "8":
            args.yes = True
            undo_last_cmd(args)
            continue

        print("无效输入，请重新选择。")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(prog="fund_predictor", description="基金预测/回测系统命令行工具")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径，默认 config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_fund_args(p):
        p.add_argument("--funds", nargs="*", default=[], help="基金代码列表，例如：009689 005827")
        p.add_argument("--fund-file", help="基金代码文件，每行一个代码")

    p1 = sub.add_parser("analyze")
    add_fund_args(p1)
    p1.set_defaults(func=analyze)

    p2 = sub.add_parser("update-data")
    add_fund_args(p2)
    p2.set_defaults(func=update_data)

    p3 = sub.add_parser("backtest")
    add_fund_args(p3)
    p3.set_defaults(func=backtest_only)

    p4 = sub.add_parser("report")
    p4.add_argument("--latest", action="store_true", help="显示最近一次生成的报告路径")
    p4.set_defaults(func=report_latest)

    # 以下为交易执行与持仓管理相关命令：
    # 1) buy: 买入/加仓
    # 2) track: 跟踪止盈止损与备注
    # 3) sell: 卖出（可用于全卖）
    # 4) partial-sell: 部分卖出（语义化命令）
    # 5) positions: 查看持仓
    # 6) history: 查看订单流水
    p5 = sub.add_parser("buy", help="登记买入或加仓")
    p5.add_argument("--fund-code", required=True, help="基金代码")
    p5.add_argument("--fund-name", default="", help="基金名称（可选）")
    p5.add_argument("--shares", type=float, required=True, help="买入份额")
    p5.add_argument("--price", type=float, required=True, help="买入单价")
    p5.add_argument("--trade-date", help="交易日期，格式 YYYY-MM-DD，默认当天")
    p5.add_argument("--note", help="备注信息")
    p5.set_defaults(func=buy_cmd)

    p6 = sub.add_parser("track", help="更新跟踪信息（止盈/止损/备注）")
    p6.add_argument("--fund-code", required=True, help="基金代码")
    p6.add_argument("--take-profit", type=float, help="止盈阈值（收益率，例如 0.12）")
    p6.add_argument("--stop-loss", type=float, help="止损阈值（收益率，例如 -0.08）")
    p6.add_argument("--note", help="跟踪备注")
    p6.set_defaults(func=track_cmd)

    p7 = sub.add_parser("sell", help="卖出基金")
    p7.add_argument("--fund-code", required=True, help="基金代码")
    p7.add_argument("--shares", type=float, required=True, help="卖出份额（全卖请填当前全部持仓）")
    p7.add_argument("--price", type=float, required=True, help="卖出单价")
    p7.add_argument("--trade-date", help="交易日期，格式 YYYY-MM-DD，默认当天")
    p7.add_argument("--note", help="卖出备注")
    p7.add_argument("--yes", action="store_true", help="跳过卖出确认")
    p7.set_defaults(func=sell_cmd)

    p8 = sub.add_parser("partial-sell", help="部分卖出基金")
    p8.add_argument("--fund-code", required=True, help="基金代码")
    p8.add_argument("--shares", type=float, required=True, help="部分卖出份额")
    p8.add_argument("--price", type=float, required=True, help="卖出单价")
    p8.add_argument("--trade-date", help="交易日期，格式 YYYY-MM-DD，默认当天")
    p8.add_argument("--note", help="部分卖出备注")
    p8.add_argument("--yes", action="store_true", help="跳过部分卖出确认")
    p8.set_defaults(func=partial_sell_cmd)

    p9 = sub.add_parser("positions", help="查看当前持仓")
    p9.set_defaults(func=positions_cmd)

    p10 = sub.add_parser("history", help="查看最近交易流水")
    p10.add_argument("--limit", type=int, default=20, help="最多显示多少条流水，默认20")
    p10.set_defaults(func=history_cmd)

    p10b = sub.add_parser("undo-last", help="撤销最近一笔订单")
    p10b.add_argument("--yes", action="store_true", help="跳过撤销确认")
    p10b.set_defaults(func=undo_last_cmd)

    p11 = sub.add_parser("init-db", help="初始化本地交易数据库")
    p11.add_argument("--reset", action="store_true", help="重置数据库（会清空历史）")
    p11.add_argument("--yes", action="store_true", help="跳过重置确认")
    p11.set_defaults(func=init_db_cmd)

    p12 = sub.add_parser("profit-summary", help="查询收益明细与概览")
    p12.set_defaults(func=profit_summary_cmd)

    p13 = sub.add_parser("console", help="交互控制台菜单")
    p13.set_defaults(func=console_cmd)

    p14 = sub.add_parser("daily-run", help="一键执行日常流程：analyze + profit-summary")

    def _daily_run_cmd(daily_args):
        # 先跑策略分析，再输出收益概览，作为日常巡检入口。
        analyze(daily_args)
        profit_summary_cmd(daily_args)
        return 0

    p14.set_defaults(func=_daily_run_cmd)
    return parser


def main() -> int:
    """程序主入口：统一捕获可预期参数/业务错误并给出中文提示。"""
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"执行失败：{exc}")
        return 1
