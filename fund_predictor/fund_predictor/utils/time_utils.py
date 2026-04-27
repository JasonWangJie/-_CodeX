from datetime import datetime


def now_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")
