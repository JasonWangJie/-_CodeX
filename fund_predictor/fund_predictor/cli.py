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


def _load_funds(args) -> list[str]:
    funds = list(args.funds or [])
    if args.fund_file:
        txt = Path(args.fund_file).read_text(encoding="utf-8")
        funds.extend([x.strip() for x in txt.splitlines() if x.strip()])
    return funds


def _persist_status(meta_dir: str, statuses: list[dict]) -> None:
    Path(meta_dir).mkdir(parents=True, exist_ok=True)
    (Path(meta_dir) / "fetch_status.json").write_text(json.dumps(statuses, ensure_ascii=False, indent=2), encoding="utf-8")


def analyze(args):
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
            continue

        idf = add_indicators(df, cfg)
        best = run_grid_search(idf, cfg)
        if not best:
            statuses[-1]["status"] = "insufficient_data"
            statuses[-1]["used_in_analysis"] = False
            continue

        latest = best["signal_df"].iloc[-1]
        ranking.append(
            {
                "fund_code": fund_code,
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
    logger.info("reports generated: %s", paths)
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
    out = Path("output/reports")
    reports = sorted(out.glob("report_*.md"))
    if not reports:
        print("No report found")
        return 1
    print(reports[-1])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fund_predictor")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_fund_args(p):
        p.add_argument("--funds", nargs="*", default=[])
        p.add_argument("--fund-file")

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
    p4.add_argument("--latest", action="store_true")
    p4.set_defaults(func=report_latest)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
