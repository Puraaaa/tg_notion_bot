"""
Media Group 收集器模块

处理 Telegram 多图消息（media group），将同一组的所有图片收集后统一处理。
"""
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

from telegram import Message, Update
from telegram.ext import CallbackContext

logger = logging.getLogger(__name__)

# Media group 收集超时时间（秒）
MEDIA_GROUP_TIMEOUT = 1.5


@dataclass
class MediaGroupData:
    """存储 media group 的数据"""
    messages: List[Message] = field(default_factory=list)
    context: Optional[CallbackContext] = None
    update: Optional[Update] = None
    timer: Optional[threading.Timer] = None
    created_at: datetime = field(default_factory=datetime.now)

    def add_message(self, message: Message):
        """按消息 ID 排序添加消息，确保顺序正确"""
        self.messages.append(message)
        self.messages.sort(key=lambda m: m.message_id)


class MediaGroupCollector:
    """
    Media Group 收集器

    收集属于同一 media_group_id 的所有消息，等待超时后统一处理。
    """

    def __init__(self, callback: Callable[[List[Message], Update, CallbackContext], None]):
        """
        初始化收集器

        参数:
            callback: 收集完成后的回调函数，接收 (messages, update, context)
        """
        self._groups: Dict[str, MediaGroupData] = {}
        self._lock = threading.Lock()
        self._callback = callback
        logger.info("MediaGroupCollector 已初始化")

    def add_message(self, update: Update, context: CallbackContext) -> bool:
        """
        添加消息到收集器

        参数:
            update: Telegram update 对象
            context: Telegram context 对象

        返回:
            bool: True 表示消息被收集（属于 media group），False 表示不是 media group
        """
        message = update.message
        media_group_id = message.media_group_id

        if not media_group_id:
            return False

        with self._lock:
            if media_group_id not in self._groups:
                # 创建新的 media group
                self._groups[media_group_id] = MediaGroupData(
                    context=context,
                    update=update
                )
                logger.info(f"创建新的 media group: {media_group_id}")

            group = self._groups[media_group_id]
            group.add_message(message)
            logger.info(
                f"Media group {media_group_id} 添加消息 {message.message_id}，"
                f"当前共 {len(group.messages)} 条"
            )

            # 取消之前的定时器
            if group.timer:
                group.timer.cancel()

            # 设置新的定时器
            group.timer = threading.Timer(
                MEDIA_GROUP_TIMEOUT,
                self._process_group,
                args=[media_group_id]
            )
            group.timer.start()

        return True

    def _process_group(self, media_group_id: str):
        """
        处理收集完成的 media group

        参数:
            media_group_id: Media group ID
        """
        with self._lock:
            if media_group_id not in self._groups:
                logger.warning(f"Media group {media_group_id} 不存在")
                return

            group = self._groups.pop(media_group_id)

        logger.info(
            f"处理 media group {media_group_id}，共 {len(group.messages)} 张图片"
        )

        try:
            self._callback(group.messages, group.update, group.context)
        except Exception as e:
            logger.error(f"处理 media group {media_group_id} 时出错: {e}")

    def get_pending_count(self) -> int:
        """获取待处理的 media group 数量"""
        with self._lock:
            return len(self._groups)


# 全局收集器实例（在 client.py 中初始化）
_collector: Optional[MediaGroupCollector] = None


def get_collector() -> Optional[MediaGroupCollector]:
    """获取全局收集器实例"""
    return _collector


def init_collector(callback: Callable[[List[Message], Update, CallbackContext], None]):
    """
    初始化全局收集器

    参数:
        callback: 收集完成后的回调函数
    """
    global _collector
    _collector = MediaGroupCollector(callback)
    return _collector
