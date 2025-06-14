"""
通知服务模块

提供各种处理状态的通知机制，跟踪长时间运行的任务
"""

import logging
import traceback
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# 保存最近的处理结果
_recent_results = {}
_last_error = None


def track_process(process_name: str):
    """
    跟踪处理过程的装饰器，记录开始、完成和错误状态

    参数:
    process_name (str): 处理名称

    用法:
    @track_process("PDF解析")
    def parse_pdf(file_path):
        # 处理代码
        return result
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            global _recent_results, _last_error
            start_time = datetime.now()
            logger.info(f"开始 {process_name} 处理...")

            try:
                result = func(*args, **kwargs)

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                # 记录处理结果
                _recent_results[process_name] = {
                    "status": "success",
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "result_type": type(result).__name__,
                }

                logger.info(f"{process_name} 处理成功完成，耗时 {duration:.2f} 秒")
                return result

            except Exception as e:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                error_details = {
                    "status": "error",
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }

                # 记录处理错误
                _recent_results[process_name] = error_details
                _last_error = error_details

                logger.error(f"{process_name} 处理失败: {e}")
                raise  # 重新抛出异常

        return wrapper

    return decorator


def get_processing_status(process_name: Optional[str] = None) -> Dict[str, Any]:
    """
    获取处理状态

    参数:
    process_name (str, optional): 特定处理名称，如果未指定返回所有处理状态

    返回:
    dict: 处理状态信息
    """
    if process_name:
        return _recent_results.get(
            process_name, {"status": "unknown", "message": "未找到处理记录"}
        )
    return _recent_results


def get_last_error() -> Optional[Dict[str, Any]]:
    """
    获取最后一个错误

    返回:
    dict: 错误详情
    """
    return _last_error


def clear_status_history():
    """清除状态历史记录"""
    global _recent_results, _last_error
    _recent_results = {}
    _last_error = None
