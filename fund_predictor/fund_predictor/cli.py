import argparse
import json
from pathlib import Path

from fund_predictor.backtest.grid_search import run_grid_search
from fund_predictor.backtest.walk_forward import append_tuning_history, run_walk_forward
from fund_predictor.config import load_config
from fund_predictor.data.fetcher import fetch_and_update_fund
from fund_predictor.features.indicators import add_indicators
from fund_predictor.report.renderer import render_reports
from fund_predictor.utils.logger import setup_logger
from fund_predictor.utils.time_utils import now_str

状态中文映射 = {
    "success": "成功",
    "fetch_failed": "抓取失败",
    "parse_failed": "解析失败",
    "insufficient_data": "样本不足",
}


def _load_funds(args) -> list[str]:
    """汇总命令行与文件中的基金代码列表。"""
    funds = list(args.funds or [])
    if args.fund_file:
        txt = Path(args.fund_file).read_text(encoding="utf-8")
        funds.extend([x.strip() for x in txt.splitlines() if x.strip()])
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
    cfg = load_config(args.config)
    logger = setup_logger("output/logs", cfg["runtime"].get("log_level", "INFO"))
    funds = _load_funds(args)
    for fund_code in funds:
        fetch_and_update_fund(fund_code, cfg, logger)
    return 0


def backtest_only(args):
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
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
