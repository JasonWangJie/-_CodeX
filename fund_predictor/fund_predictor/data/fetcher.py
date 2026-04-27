from datetime import datetime, timedelta
from typing import Any
import re

import pandas as pd
import requests

from fund_predictor.data.parser import parse_pages, parse_records_table
from fund_predictor.data.schema import FundFetchStatus
from fund_predictor.data.storage import load_nav, save_nav
from fund_predictor.utils.exceptions import FetchError, ParseError
from fund_predictor.utils.retry import retry_call

NAME_RE = re.compile(r"(.+?)\((\d{6})\)")


def _request(session: requests.Session, base_url: str, params: dict[str, Any], timeout: int, retry_times: int, retry_sleep: float) -> str:
    """统一的网络请求封装：带重试、超时、HTTP状态码校验。"""

    def _do() -> str:
        resp = session.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    try:
        return retry_call(_do, retry_times=retry_times, sleep_seconds=retry_sleep)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc


def _fetch_fund_name(session: requests.Session, fund_code: str, timeout: int, retry_times: int, retry_sleep: float) -> str:
    """
    通过基金详情页标题提取基金中文名称。
    - 示例标题常见格式：`某某基金(009689) ...`
    - 失败时返回空字符串，由上层决定降级文案。
    """

    url = f"https://fund.eastmoney.com/{fund_code}.html"

    def _do() -> str:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    try:
        html = retry_call(_do, retry_times=retry_times, sleep_seconds=retry_sleep)
    except Exception:  # noqa: BLE001
        return ""

    # 优先解析 <title>，避免依赖更复杂的DOM结构。
    title_start = html.find("<title>")
    title_end = html.find("</title>")
    if title_start < 0 or title_end < 0:
        return ""
    title = html[title_start + len("<title>") : title_end].strip()
    match = NAME_RE.search(title)
    if not match:
        return ""
    return match.group(1).strip()


def fetch_and_update_fund(fund_code: str, cfg: dict[str, Any], logger) -> tuple[pd.DataFrame, FundFetchStatus]:
    """
    拉取并更新单只基金净值数据。
    关键点：
    1) 首次运行全量拉取；后续按本地最后日期增量更新。
    2) 任意异常只影响当前基金，不中断整个批次。
    3) 返回结构化状态对象，便于报告展示失败原因与置信度处理。
    """

    ds = cfg["data_source"]
    st = cfg["storage"]
    existing = load_nav(st["nav_dir"], fund_code, st["file_format"])
    start_date = None
    if not existing.empty and ds.get("use_incremental_update", True):
        start_date = (pd.to_datetime(existing["nav_date"]).max() + timedelta(days=1)).strftime("%Y-%m-%d")

    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    session = requests.Session()
    fund_name = _fetch_fund_name(session, fund_code, ds["timeout_seconds"], ds["retry_times"], ds["retry_sleep_seconds"])

    try:
        page = 1
        records = []
        total_pages = 1
        while page <= total_pages:
            params = {
                "type": "lsjz",
                "code": fund_code,
                "page": page,
                "per": ds["per_page"],
                "edate": end_date,
            }
            if start_date:
                params["sdate"] = start_date
            text = _request(
                session,
                ds["base_url"],
                params,
                ds["timeout_seconds"],
                ds["retry_times"],
                ds["retry_sleep_seconds"],
            )
            total_pages = parse_pages(text)
            page_df = parse_records_table(text)
            if page_df.empty and start_date:
                break
            records.append(page_df)
            page += 1

        new_df = pd.concat(records, ignore_index=True) if records else pd.DataFrame(columns=["nav_date", "unit_nav", "acc_nav", "daily_growth"])
        new_df["fund_code"] = fund_code
        new_df["fund_name"] = fund_name
        new_df["source"] = "eastmoney"
        new_df["fetch_time"] = datetime.utcnow()

        merged = pd.concat([existing, new_df], ignore_index=True)
        if not merged.empty:
            merged = merged.drop_duplicates(subset=["nav_date"], keep="last").sort_values("nav_date").reset_index(drop=True)
            # 若历史文件缺少 fund_name 列，这里做兼容补齐。
            if "fund_name" not in merged.columns:
                merged["fund_name"] = fund_name
            else:
                merged["fund_name"] = merged["fund_name"].fillna("").replace("", fund_name)
        save_nav(merged, st["nav_dir"], fund_code, st["file_format"])
        status = FundFetchStatus(fund_code=fund_code, fund_name=fund_name, status="success", used_in_analysis=True)
        return merged, status
    except (FetchError, ParseError) as exc:
        logger.exception("基金 %s 数据获取失败", fund_code)
        status = FundFetchStatus(
            fund_code=fund_code,
            fund_name=fund_name,
            status="fetch_failed" if isinstance(exc, FetchError) else "parse_failed",
            reason=str(exc),
            retry_count=ds["retry_times"],
            used_in_analysis=False,
        )
        return existing, status
