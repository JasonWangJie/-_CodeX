from dataclasses import dataclass


@dataclass
class FundFetchStatus:
    fund_code: str
    status: str
    reason: str = ""
    retry_count: int = 0
    used_in_analysis: bool = False
