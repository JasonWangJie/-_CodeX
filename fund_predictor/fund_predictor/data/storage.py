from pathlib import Path
from collections import OrderedDict
import sqlite3

import pandas as pd

_MEM_CACHE: "OrderedDict[str, pd.DataFrame]" = OrderedDict()


def _file_path(nav_dir: str, fund_code: str, fmt: str) -> Path:
    return Path(nav_dir) / f"{fund_code}.{fmt}"


def _cache_key(fund_code: str, backend: str, store_id: str) -> str:
    return f"{backend}:{store_id}:{fund_code}"


def _get_mem_cache(key: str) -> pd.DataFrame | None:
    if key not in _MEM_CACHE:
        return None
    # LRU：命中后移动到末尾。
    _MEM_CACHE.move_to_end(key)
    return _MEM_CACHE[key].copy()


def _put_mem_cache(key: str, value: pd.DataFrame, max_size: int) -> None:
    _MEM_CACHE[key] = value.copy()
    _MEM_CACHE.move_to_end(key)
    while len(_MEM_CACHE) > max_size:
        _MEM_CACHE.popitem(last=False)


def _ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS nav_history (
            fund_code TEXT NOT NULL,
            nav_date TEXT NOT NULL,
            unit_nav REAL,
            acc_nav REAL,
            daily_growth REAL,
            fund_name TEXT,
            source TEXT,
            fetch_time TEXT,
            PRIMARY KEY (fund_code, nav_date)
        )
        """
    )
    conn.commit()


def _load_from_sqlite(sqlite_path: str, fund_code: str) -> pd.DataFrame:
    path = Path(sqlite_path)
    if not path.exists():
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        _ensure_sqlite_schema(conn)
        df = pd.read_sql_query(
            "SELECT * FROM nav_history WHERE fund_code = ? ORDER BY nav_date ASC",
            conn,
            params=[fund_code],
        )
    if df.empty:
        return df
    df["nav_date"] = pd.to_datetime(df["nav_date"], errors="coerce")
    return df


def _save_to_sqlite(sqlite_path: str, fund_code: str, df: pd.DataFrame) -> None:
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        _ensure_sqlite_schema(conn)
        # 先删再写，确保同一基金数据幂等更新，逻辑简单稳定。
        conn.execute("DELETE FROM nav_history WHERE fund_code = ?", [fund_code])
        write_df = df.copy()
        if not write_df.empty:
            write_df["nav_date"] = pd.to_datetime(write_df["nav_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            write_df["fetch_time"] = write_df.get("fetch_time")
            write_df.to_sql("nav_history", conn, if_exists="append", index=False)
        conn.commit()


def load_nav(
    nav_dir: str,
    fund_code: str,
    fmt: str,
    *,
    backend: str = "file",
    sqlite_path: str = "data/meta/nav_cache.db",
    use_memory_cache: bool = True,
    memory_cache_size: int = 128,
) -> pd.DataFrame:
    """
    加载基金净值缓存，支持三级策略：
    1) 内存缓存（可选，最快）
    2) SQLite（backend=sqlite）
    3) 文件缓存 parquet/csv（backend=file）
    """
    store_id = sqlite_path if backend == "sqlite" else nav_dir
    key = _cache_key(fund_code, backend, store_id)
    if use_memory_cache:
        cached = _get_mem_cache(key)
        if cached is not None:
            return cached

    if backend == "sqlite":
        df = _load_from_sqlite(sqlite_path, fund_code)
    else:
        path = _file_path(nav_dir, fund_code, fmt)
        if not path.exists():
            df = pd.DataFrame()
        elif fmt == "parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, parse_dates=["nav_date"])

    if use_memory_cache:
        _put_mem_cache(key, df, memory_cache_size)
    return df


def save_nav(
    df: pd.DataFrame,
    nav_dir: str,
    fund_code: str,
    fmt: str,
    *,
    backend: str = "file",
    sqlite_path: str = "data/meta/nav_cache.db",
    use_memory_cache: bool = True,
    memory_cache_size: int = 128,
) -> None:
    """
    保存基金净值缓存，并同步更新内存缓存。
    """
    if backend == "sqlite":
        _save_to_sqlite(sqlite_path, fund_code, df)
    else:
        Path(nav_dir).mkdir(parents=True, exist_ok=True)
        path = _file_path(nav_dir, fund_code, fmt)
        if fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)

    if use_memory_cache:
        store_id = sqlite_path if backend == "sqlite" else nav_dir
        key = _cache_key(fund_code, backend, store_id)
        _put_mem_cache(key, df, memory_cache_size)
