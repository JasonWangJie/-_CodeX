import re

from fund_predictor.utils.retry import retry_call
from fund_predictor.utils.time_utils import now_str


def test_retry_call_retries_then_succeeds():
    state = {"count": 0}

    def flaky():
        state["count"] += 1
        if state["count"] < 3:
            raise ValueError("temporary")
        return "ok"

    out = retry_call(flaky, retry_times=3, sleep_seconds=0)
    assert out == "ok"
    assert state["count"] == 3


def test_now_str_format():
    assert re.fullmatch(r"\d{8}_\d{6}", now_str())
