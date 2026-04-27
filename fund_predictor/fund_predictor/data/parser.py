import re

import pandas as pd
from bs4 import BeautifulSoup

from fund_predictor.utils.exceptions import ParseError

PAGES_RE = re.compile(r"pages:(\d+)")


def parse_pages(raw_text: str) -> int:
    """从接口返回的JS片段中提取总页数。"""
    match = PAGES_RE.search(raw_text)
    if not match:
        raise ParseError("无法从响应内容中解析总页数 pages")
    return int(match.group(1))


def parse_records_table(raw_text: str) -> pd.DataFrame:
    """从接口返回的HTML表格中解析净值记录。"""
    start = raw_text.find("<table")
    end = raw_text.rfind("</table>")
    if start < 0 or end < 0:
        raise ParseError("响应中未找到净值表格")
    html = raw_text[start : end + len("</table>")]
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        raise ParseError("净值表格为空")

    rows = []
    for tr in table.find_all("tr"):
        cols = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if len(cols) >= 4 and cols[0] != "净值日期":
            rows.append(cols)
    if not rows:
        return pd.DataFrame(columns=["nav_date", "unit_nav", "acc_nav", "daily_growth"])

    df = pd.DataFrame(rows, columns=["nav_date", "unit_nav", "acc_nav", "daily_growth", *range(max(0, len(rows[0]) - 4))])
    df = df[["nav_date", "unit_nav", "acc_nav", "daily_growth"]].copy()
    df["nav_date"] = pd.to_datetime(df["nav_date"], errors="coerce")
    for col in ["unit_nav", "acc_nav"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["daily_growth"] = pd.to_numeric(df["daily_growth"].str.replace("%", "", regex=False), errors="coerce") / 100
    return df.dropna(subset=["nav_date"])
