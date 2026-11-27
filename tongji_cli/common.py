from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


class QueryUnavailable(Exception):
    pass


def failure(error):
    message = str(error) if isinstance(error, QueryUnavailable) else "页面或数据格式未能核实"
    return {"status": "unverified", "detail": message}
