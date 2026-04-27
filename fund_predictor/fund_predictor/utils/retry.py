import time
from typing import Callable, TypeVar

T = TypeVar("T")


def retry_call(func: Callable[[], T], retry_times: int, sleep_seconds: float) -> T:
    last_exc = None
    for i in range(retry_times + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if i < retry_times:
                time.sleep(sleep_seconds)
    raise last_exc  # type: ignore[misc]
