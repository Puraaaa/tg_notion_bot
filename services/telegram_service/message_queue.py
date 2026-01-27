"""
Telegram Bot 消息队列处理模块
实现断联重连后的消息队列处理机制
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import telegram
from telegram import Update
from telegram.ext import Updater

logger = logging.getLogger(__name__)


class MessageOffsetManager:
    """消息偏移量管理器，负责持久化存储和管理 update_id"""

    def __init__(self, storage_path: str = "data/message_offset.db"):
        """
        初始化偏移量管理器

        Args:
            storage_path: 存储文件路径
        """
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS message_offset (
                        id INTEGER PRIMARY KEY,
                        last_update_id INTEGER NOT NULL,
                        last_processed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # 创建处理历史表，防止重复处理
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_messages (
                        update_id INTEGER PRIMARY KEY,
                        message_id INTEGER,
                        chat_id INTEGER,
                        processed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        message_type TEXT
                    )
                """)

                conn.commit()
                logger.info(f"消息偏移量数据库初始化完成: {self.storage_path}")
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}")
            raise

    def get_last_offset(self) -> Optional[int]:
        """
        获取最后处理的消息偏移量

        Returns:
            最后的 update_id，如果没有则返回 None
        """
        try:
            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT MAX(last_update_id) FROM message_offset
                """)
                result = cursor.fetchone()
                if result and result[0] is not None:
                    logger.info(f"获取到最后偏移量: {result[0]}")
                    return result[0]
                else:
                    logger.info("未找到历史偏移量记录")
                    return None
        except Exception as e:
            logger.error(f"获取偏移量失败: {e}")
            return None

    def update_offset(self, update_id: int):
        """
        更新最后处理的消息偏移量

        Args:
            update_id: 新的 update_id
        """
        try:
            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO message_offset (last_update_id)
                    VALUES (?)
                """, (update_id,))
                conn.commit()
                logger.debug(f"更新偏移量: {update_id}")
        except Exception as e:
            logger.error(f"更新偏移量失败: {e}")

    def is_message_processed(self, update_id: int) -> bool:
        """
        检查消息是否已经被处理过

        Args:
            update_id: 要检查的 update_id

        Returns:
            True 如果已处理，False 如果未处理
        """
        try:
            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM processed_messages
                    WHERE update_id = ?
                """, (update_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查消息处理状态失败: {e}")
            return False

    def mark_message_processed(self, update: Update):
        """
        标记消息为已处理

        Args:
            update: Telegram Update 对象
        """
        try:
            message_id = None
            chat_id = None
            message_type = "unknown"

            if update.message:
                message_id = update.message.message_id
                chat_id = update.message.chat_id
                message_type = "message"
            elif update.callback_query:
                message_type = "callback_query"
                if update.callback_query.message:
                    message_id = update.callback_query.message.message_id
                    chat_id = update.callback_query.message.chat_id

            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO processed_messages
                    (update_id, message_id, chat_id, message_type)
                    VALUES (?, ?, ?, ?)
                """, (update.update_id, message_id, chat_id, message_type))
                conn.commit()
                logger.debug(f"标记消息已处理: update_id={update.update_id}")
        except Exception as e:
            logger.error(f"标记消息处理状态失败: {e}")

    def cleanup_old_records(self, days: int = 7):
        """
        清理旧的处理记录

        Args:
            days: 保留天数
        """
        try:
            with sqlite3.connect(self.storage_path) as conn:
                cursor = conn.cursor()

                # 清理旧的偏移量记录，只保留最新的几条
                cursor.execute("""
                    DELETE FROM message_offset
                    WHERE id NOT IN (
                        SELECT id FROM message_offset
                        ORDER BY last_processed_time DESC
                        LIMIT 10
                    )
                """)

                # 清理旧的处理记录
                cursor.execute("""
                    DELETE FROM processed_messages
                    WHERE processed_time < datetime('now', '-{} days')
                """.format(days))

                conn.commit()
                logger.info(f"清理了 {days} 天前的旧记录")
        except Exception as e:
            logger.error(f"清理旧记录失败: {e}")


class MessageQueueProcessor:
    """消息队列处理器，负责处理断联期间的积压消息"""

    def __init__(self, bot: telegram.Bot, offset_manager: MessageOffsetManager):
        """
        初始化消息队列处理器

        Args:
            bot: Telegram Bot 实例
            offset_manager: 偏移量管理器
        """
        self.bot = bot
        self.offset_manager = offset_manager
        self.batch_size = 100  # 每批处理的消息数量
        self.processing_delay = 0.1  # 处理间隔，避免 API 限流

    def get_pending_updates(self, offset: Optional[int] = None, limit: int = 100) -> List[Update]:
        """
        获取待处理的更新

        Args:
            offset: 起始偏移量
            limit: 获取数量限制

        Returns:
            Update 对象列表
        """
        try:
            logger.info(f"获取待处理更新，offset={offset}, limit={limit}")

            # 使用 getUpdates 方法获取消息
            updates = self.bot.get_updates(
                offset=offset,
                limit=limit,
                timeout=10,
                allowed_updates=None  # 获取所有类型的更新
            )

            logger.info(f"获取到 {len(updates)} 条待处理更新")
            return updates

        except telegram.error.TelegramError as e:
            logger.error(f"获取更新失败: {e}")
            return []
        except Exception as e:
            logger.error(f"获取更新时发生未知错误: {e}")
            return []

    def process_backlog_messages(self, message_handlers: Dict) -> Tuple[int, int]:
        """
        处理积压的消息

        Args:
            message_handlers: 消息处理器字典

        Returns:
            (处理成功数量, 处理失败数量)
        """
        processed_count = 0
        failed_count = 0

        # 获取最后的偏移量
        last_offset = self.offset_manager.get_last_offset()
        current_offset = last_offset + 1 if last_offset is not None else None

        logger.info(f"开始处理积压消息，起始偏移量: {current_offset}")

        while True:
            # 获取一批待处理的更新
            updates = self.get_pending_updates(offset=current_offset, limit=self.batch_size)

            if not updates:
                logger.info("没有更多待处理的消息")
                break

            logger.info(f"处理 {len(updates)} 条消息，偏移量范围: {updates[0].update_id} - {updates[-1].update_id}")

            for update in updates:
                try:
                    # 检查是否已经处理过
                    if self.offset_manager.is_message_processed(update.update_id):
                        logger.debug(f"跳过已处理的消息: {update.update_id}")
                        continue

                    # 处理消息
                    success = self._process_single_update(update, message_handlers)

                    if success:
                        # 标记为已处理
                        self.offset_manager.mark_message_processed(update)
                        # 更新偏移量
                        self.offset_manager.update_offset(update.update_id)
                        processed_count += 1
                    else:
                        failed_count += 1

                    # 更新当前偏移量
                    current_offset = update.update_id + 1

                    # 添加处理延迟，避免 API 限流
                    time.sleep(self.processing_delay)

                except Exception as e:
                    logger.error(f"处理消息 {update.update_id} 时发生错误: {e}")
                    failed_count += 1
                    current_offset = update.update_id + 1

            # 如果获取的消息数量少于批次大小，说明已经处理完所有积压消息
            if len(updates) < self.batch_size:
                break

        logger.info(f"积压消息处理完成，成功: {processed_count}, 失败: {failed_count}")
        return processed_count, failed_count

    def _process_single_update(self, update: Update, message_handlers: Dict) -> bool:
        """
        处理单个更新

        Args:
            update: Telegram Update 对象
            message_handlers: 消息处理器字典

        Returns:
            True 如果处理成功，False 如果处理失败
        """
        try:
            # 根据更新类型选择合适的处理器
            if update.message:
                handler = message_handlers.get('message')
                if handler:
                    handler(update, None)  # 这里的 context 在批量处理时可能为 None
                    return True
            elif update.callback_query:
                handler = message_handlers.get('callback_query')
                if handler:
                    handler(update, None)
                    return True
            elif update.inline_query:
                handler = message_handlers.get('inline_query')
                if handler:
                    handler(update, None)
                    return True

            logger.warning(f"未找到合适的处理器处理更新类型: {type(update)}")
            return False

        except Exception as e:
            logger.error(f"处理更新时发生错误: {e}")
            return False


class ReconnectionManager:
    """重连管理器，负责检测断联和触发消息恢复"""

    def __init__(self, bot: telegram.Bot, queue_processor: MessageQueueProcessor):
        """
        初始化重连管理器

        Args:
            bot: Telegram Bot 实例
            queue_processor: 消息队列处理器
        """
        self.bot = bot
        self.queue_processor = queue_processor
        self.last_connection_check = time.time()
        self.connection_check_interval = 300  # 5分钟检查一次连接
        self.is_recovering = False

    def check_connection_and_recover(self, message_handlers: Dict) -> bool:
        """
        检查连接状态并在需要时恢复消息

        Args:
            message_handlers: 消息处理器字典

        Returns:
            True 如果连接正常或恢复成功，False 如果连接失败
        """
        current_time = time.time()

        # 检查是否需要进行连接检查
        if current_time - self.last_connection_check < self.connection_check_interval:
            return True

        self.last_connection_check = current_time

        try:
            # 测试连接
            self.bot.get_me()
            logger.debug("Telegram 连接正常")

            # 如果之前在恢复状态，现在连接正常了，处理积压消息
            if self.is_recovering:
                logger.info("检测到重连成功，开始处理积压消息")
                self._recover_messages(message_handlers)
                self.is_recovering = False

            return True

        except telegram.error.NetworkError as e:
            logger.warning(f"Telegram 连接异常: {e}")
            self.is_recovering = True
            return False
        except Exception as e:
            logger.error(f"连接检查时发生未知错误: {e}")
            self.is_recovering = True
            return False

    def _recover_messages(self, message_handlers: Dict):
        """
        恢复积压的消息

        Args:
            message_handlers: 消息处理器字典
        """
        try:
            logger.info("开始恢复积压消息")
            processed, failed = self.queue_processor.process_backlog_messages(message_handlers)
            logger.info(f"消息恢复完成，处理成功: {processed}, 失败: {failed}")
        except Exception as e:
            logger.error(f"消息恢复过程中发生错误: {e}")