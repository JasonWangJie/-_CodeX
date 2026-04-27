from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from fund_predictor.data.parser import parse_pages, parse_records_table
from fund_predictor.data.schema import FundFetchStatus
from fund_predictor.data.storage import load_nav, save_nav
from fund_predictor.utils.exceptions import FetchError, ParseError
from fund_predictor.utils.retry import retry_call


def _request(session: requests.Session, base_url: str, params: dict[str, Any], timeout: int, retry_times: int, retry_sleep: float) -> str:
    def _do() -> str:
        resp = session.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.text

    try:
        return retry_call(_do, retry_times=retry_times, sleep_seconds=retry_sleep)
    except Exception as exc:  # noqa: BLE001
        raise FetchError(str(exc)) from exc


def fetch_and_update_fund(fund_code: str, cfg: dict[str, Any], logger) -> tuple[pd.DataFrame, FundFetchStatus]:
    ds = cfg["data_source"]
    st = cfg["storage"]
    existing = load_nav(st["nav_dir"], fund_code, st["file_format"])
    start_date = None
    if not existing.empty and ds.get("use_incremental_update", True):
        start_date = (pd.to_datetime(existing["nav_date"]).max() + timedelta(days=1)).strftime("%Y-%m-%d")

    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    session = requests.Session()

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
        new_df["source"] = "eastmoney"
        new_df["fetch_time"] = datetime.utcnow()

        merged = pd.concat([existing, new_df], ignore_index=True)
        if not merged.empty:
            merged = merged.drop_duplicates(subset=["nav_date"], keep="last").sort_values("nav_date").reset_index(drop=True)
        save_nav(merged, st["nav_dir"], fund_code, st["file_format"])
        status = FundFetchStatus(fund_code=fund_code, status="success", used_in_analysis=True)
        return merged, status
    except (FetchError, ParseError) as exc:
        logger.exception("Failed to fetch %s", fund_code)
        status = FundFetchStatus(
            fund_code=fund_code,
            status="fetch_failed" if isinstance(exc, FetchError) else "parse_failed",
            reason=str(exc),
            retry_count=ds["retry_times"],
            used_in_analysis=False,
        )
        return existing, status
