#!/usr/bin/env python3
"""
消息队列处理功能演示脚本
展示断联重连后的消息队列处理机制
"""

import logging
import os
import tempfile
from unittest.mock import Mock

import telegram
from telegram import Update, Message, User, Chat

from services.telegram_service.message_queue import (
    MessageOffsetManager,
    MessageQueueProcessor,
    ReconnectionManager,
)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def create_mock_update(update_id, text="test message"):
    """创建模拟的 Update 对象"""
    user = User(id=1, first_name="TestUser", is_bot=False)
    chat = Chat(id=1, type="private")
    message = Message(
        message_id=update_id,
        date=None,
        chat=chat,
        from_user=user,
        text=text
    )
    return Update(update_id=update_id, message=message)


def demo_message_queue_processing():
    """演示消息队列处理功能"""
    logger.info("=== 消息队列处理功能演示 ===")

    # 创建临时数据库
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db.close()

    try:
        # 1. 初始化组件
        logger.info("1. 初始化消息队列组件...")
        offset_manager = MessageOffsetManager(temp_db.name)

        # 创建模拟的 Bot
        mock_bot = Mock(spec=telegram.Bot)
        queue_processor = MessageQueueProcessor(mock_bot, offset_manager)
        reconnection_manager = ReconnectionManager(mock_bot, queue_processor)

        # 2. 模拟正常消息处理
        logger.info("2. 模拟正常消息处理...")
        for i in range(1, 6):
            update = create_mock_update(i, f"正常消息 {i}")
            offset_manager.mark_message_processed(update)
            offset_manager.update_offset(i)
            logger.info(f"   处理消息 {i}: {update.message.text}")

        # 检查当前偏移量
        current_offset = offset_manager.get_last_offset()
        logger.info(f"   当前偏移量: {current_offset}")

        # 3. 模拟断联期间的消息积压
        logger.info("3. 模拟断联期间的消息积压...")
        backlog_messages = []
        for i in range(6, 16):  # 模拟10条积压消息
            update = create_mock_update(i, f"积压消息 {i}")
            backlog_messages.append(update)

        # 模拟 bot.get_updates 返回积压消息
        def mock_get_updates(offset=None, limit=100, **kwargs):
            if offset and offset > 15:
                return []  # 没有更多消息
            return backlog_messages

        mock_bot.get_updates.side_effect = mock_get_updates

        # 4. 模拟重连后的消息恢复
        logger.info("4. 模拟重连后的消息恢复...")

        # 创建消息处理器
        processed_messages = []
        def message_handler(update, context):
            processed_messages.append(update.update_id)
            logger.info(f"   恢复处理消息 {update.update_id}: {update.message.text}")

        message_handlers = {'message': message_handler}

        # 处理积压消息
        processed, failed = queue_processor.process_backlog_messages(message_handlers)
        logger.info(f"   积压消息处理完成: 成功 {processed} 条, 失败 {failed} 条")

        # 5. 验证消息处理状态
        logger.info("5. 验证消息处理状态...")
        final_offset = offset_manager.get_last_offset()
        logger.info(f"   最终偏移量: {final_offset}")

        # 检查消息是否被正确标记为已处理
        for i in range(6, 16):
            is_processed = offset_manager.is_message_processed(i)
            logger.info(f"   消息 {i} 处理状态: {'已处理' if is_processed else '未处理'}")

        # 6. 演示重连管理器
        logger.info("6. 演示重连管理器...")

        # 模拟连接正常
        mock_bot.get_me.return_value = Mock()
        reconnection_manager.connection_check_interval = 0  # 立即检查

        result = reconnection_manager.check_connection_and_recover(message_handlers)
        logger.info(f"   连接检查结果: {'正常' if result else '异常'}")

        # 模拟连接异常
        mock_bot.get_me.side_effect = telegram.error.NetworkError("连接失败")
        result = reconnection_manager.check_connection_and_recover(message_handlers)
        logger.info(f"   连接异常检查结果: {'正常' if result else '异常'}")
        logger.info(f"   恢复状态: {'正在恢复' if reconnection_manager.is_recovering else '正常'}")

        # 7. 清理演示
        logger.info("7. 清理旧记录...")
        offset_manager.cleanup_old_records(days=0)  # 立即清理用于演示
        logger.info("   清理完成")

        logger.info("=== 演示完成 ===")

    finally:
        # 清理临时文件
        os.unlink(temp_db.name)


def demo_large_message_batch():
    """演示大量消息批处理"""
    logger.info("=== 大量消息批处理演示 ===")

    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db.close()

    try:
        offset_manager = MessageOffsetManager(temp_db.name)
        mock_bot = Mock(spec=telegram.Bot)
        queue_processor = MessageQueueProcessor(mock_bot, offset_manager)

        # 创建大量消息（120条）
        large_batch = [create_mock_update(i, f"批量消息 {i}") for i in range(1, 121)]
        logger.info(f"创建了 {len(large_batch)} 条模拟消息")

        # 模拟分批返回
        call_count = 0
        def mock_get_updates(offset=None, limit=100, **kwargs):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                logger.info("   返回第一批消息 (1-100)")
                return large_batch[:100]
            elif call_count == 2:
                logger.info("   返回第二批消息 (101-120)")
                return large_batch[100:120]
            else:
                logger.info("   没有更多消息")
                return []

        mock_bot.get_updates.side_effect = mock_get_updates

        # 处理消息
        processed_count = 0
        def batch_handler(update, context):
            nonlocal processed_count
            processed_count += 1
            if processed_count % 20 == 0:  # 每20条消息打印一次进度
                logger.info(f"   已处理 {processed_count} 条消息...")

        message_handlers = {'message': batch_handler}

        # 执行批量处理
        logger.info("开始批量处理...")
        processed, failed = queue_processor.process_backlog_messages(message_handlers)

        logger.info(f"批量处理完成: 成功 {processed} 条, 失败 {failed} 条")
        logger.info("=== 大量消息批处理演示完成 ===")

    finally:
        os.unlink(temp_db.name)


if __name__ == "__main__":
    print("Telegram Bot 消息队列处理功能演示")
    print("=" * 50)

    # 运行基本功能演示
    demo_message_queue_processing()
    print()

    # 运行大量消息批处理演示
    demo_large_message_batch()

    print("\n演示脚本执行完成！")
    print("\n功能特性总结:")
    print("✅ 消息偏移量持久化存储")
    print("✅ 防止消息重复处理")
    print("✅ 断联重连后自动恢复积压消息")
    print("✅ 批量处理大量积压消息")
    print("✅ 错误处理和重试机制")
    print("✅ 连接状态监控和自动恢复")