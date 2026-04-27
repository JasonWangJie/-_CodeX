import json
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader


def render_reports(context: dict, output_dir: str, stamp: str) -> dict:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    tpl_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(tpl_dir), autoescape=False)

    md = env.get_template("report.md.j2").render(**context)
    html = env.get_template("report.html.j2").render(**context)

    md_path = Path(output_dir) / f"report_{stamp}.md"
    html_path = Path(output_dir) / f"report_{stamp}.html"
    json_path = Path(output_dir) / f"report_{stamp}.json"
    csv_path = Path(output_dir) / f"trades_{stamp}.csv"

    md_path.write_text(md, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    json_path.write_text(json.dumps(context, ensure_ascii=False, default=str, indent=2), encoding="utf-8")

    trades = []
    for x in context.get("ranking", []):
        t = x.get("trades")
        if isinstance(t, pd.DataFrame) and not t.empty:
            tmp = t.copy()
            tmp["fund_code"] = x["fund_code"]
            trades.append(tmp)
    all_trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    all_trades.to_csv(csv_path, index=False)

    return {"md": str(md_path), "html": str(html_path), "json": str(json_path), "csv": str(csv_path)}
