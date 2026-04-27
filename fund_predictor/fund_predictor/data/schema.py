from dataclasses import dataclass


@dataclass
class FundFetchStatus:
    # 基金代码（例如：009689）
    fund_code: str
    # 基金名称（例如：某某成长混合）；若获取失败则可能为空字符串
    fund_name: str
    # 处理状态：success / fetch_failed / parse_failed / insufficient_data
    status: str
    # 失败原因，成功时为空
    reason: str = ""
    # 重试次数（不含首次请求）
    retry_count: int = 0
    # 是否进入后续分析（特征、回测、排序）
    used_in_analysis: bool = False
