from pathlib import Path

import pandas as pd


def _file_path(nav_dir: str, fund_code: str, fmt: str) -> Path:
    return Path(nav_dir) / f"{fund_code}.{fmt}"


def load_nav(nav_dir: str, fund_code: str, fmt: str) -> pd.DataFrame:
    path = _file_path(nav_dir, fund_code, fmt)
    if not path.exists():
        return pd.DataFrame()
    if fmt == "parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, parse_dates=["nav_date"])


def save_nav(df: pd.DataFrame, nav_dir: str, fund_code: str, fmt: str) -> None:
    Path(nav_dir).mkdir(parents=True, exist_ok=True)
    path = _file_path(nav_dir, fund_code, fmt)
    if fmt == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
