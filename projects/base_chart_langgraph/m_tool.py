from langchain_core.tools import tool


@tool
def sum_numbers(a: float, b: float) -> float:
    """计算两个数字 a 和 b 的和，并返回求和结果。"""
    return a + b

@tool
def get_current_time() -> str:
    """获取当前时间。"""
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
