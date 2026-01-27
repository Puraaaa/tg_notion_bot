#!/usr/bin/env python3
"""
Telegram Notion Bot 主程序入口
整合 bot_main 和 main 的功能，统一处理 SSL 证书验证和机器人初始化
"""

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import schedule

# 导入 telegram 相关模块
import telegram
from dotenv import load_dotenv
from telegram.ext import Updater
from telegram.utils.request import Request

# 导入其他服务和配置
from config import (
    ALLOWED_USER_IDS,
    LOG_LEVEL,
    TELEGRAM_BOT_TOKEN,
    WEEKLY_REPORT_DAY,
    WEEKLY_REPORT_HOUR,
)
from services.telegram_service import (
    MessageOffsetManager,
    MessageQueueProcessor,
    ReconnectionManager,
    setup_telegram_bot,
)
from services.weekly_report import generate_weekly_report
from utils.keep_alive import KEEP_ALIVE

# 导入智能代理设置（替代 SSL helper）
from utils.smart_proxy import configure_proxy_for_telegram, test_connectivity

# 导入参数验证工具
from utils.telegram_helper import (
    clear_webhook,
    monitor_telegram_webhook,
    validate_request_kwargs,
)

# 添加项目根目录到 Python 路径
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))

# 首先加载环境变量，确保设置可用
load_dotenv()


# 确保日志目录存在
os.makedirs(os.path.join(root_dir, "logs"), exist_ok=True)

# 配置日志系统
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL),
    handlers=[
        logging.FileHandler(os.path.join(root_dir, "logs", "bot.log"), mode="a"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# 全局设置
MAX_RETRIES = 5
RETRY_DELAY = 5  # seconds
should_exit = False
connection_check_interval = 600  # 10 分钟检查一次连接


def init_bot(
    token: str, disable_certificate_verification: bool = False
) -> Optional[Updater]:
    """
    初始化 Telegram 机器人，提供证书验证选项

    参数：
        token: Telegram Bot API 令牌
        disable_certificate_verification: 是否禁用 SSL 证书验证

    返回：
        Updater 对象，如果初始化成功
    """
    retry_count = 0
    max_retries = MAX_RETRIES

    while retry_count < max_retries:
        try:
            # 使用智能代理配置获取请求参数
            request_kwargs = configure_proxy_for_telegram()

            # 验证和过滤请求参数
            valid_request_kwargs = validate_request_kwargs(request_kwargs)

            # 创建请求对象
            logger.debug(f"Request 参数：{valid_request_kwargs}")
            request = Request(**valid_request_kwargs)

            # 创建 Bot 对象
            bot = telegram.Bot(token=token, request=request)

            # 确保没有活动的 webhook（webhook 会阻止轮询工作）
            if monitor_telegram_webhook(bot):
                logger.warning("发现活动的 webhook 配置，正在尝试清除...")
                clear_webhook(bot)

            # 测试连接
            logger.info("正在测试与 Telegram API 的连接...")
            bot_info = bot.get_me()
            logger.info(f"成功连接到 Telegram! 机器人名称：{bot_info.first_name}")

            # 创建并返回 updater
            updater = Updater(bot=bot)
            # 打印 updater 信息以确认初始化成功
            logger.info(f"成功创建 Updater 实例：{updater}")
            return updater

        except telegram.error.NetworkError as e:
            retry_count += 1
            err_msg = str(e)
            # 对一些特定错误提供更详细的诊断
            if "EOF occurred in violation of protocol" in err_msg:
                logger.warning(f"SSL 连接中断错误，可能是代理问题：{e}")
            elif "certificate verify failed" in err_msg:
                logger.warning(f"SSL 证书验证失败：{e}")
            else:
                logger.warning(f"网络错误：{e}")

            logger.warning(f"尝试重新连接 ({retry_count}/{max_retries})...")
            time.sleep(RETRY_DELAY * (retry_count**0.5))  # 逐渐增加等待时间

        except Exception as e:
            logger.error(f"初始化机器人时出错：{e}", exc_info=True)
            return None

    logger.error(f"在 {max_retries} 次尝试后仍无法连接到 Telegram")
    return None


# 全局变量，用于存储 updater 实例和消息队列组件
_updater = None
_offset_manager = None
_queue_processor = None
_reconnection_manager = None


def schedule_weekly_report():
    """安排周报生成任务"""
    schedule_day = WEEKLY_REPORT_DAY.lower()
    schedule_hour = f"{WEEKLY_REPORT_HOUR:02d}:00"

    def scheduled_weekly_report():
        """定时任务包装函数，传入 bot 和用户 ID"""
        if _updater and _updater.bot:
            generate_weekly_report(
                bot=_updater.bot, chat_ids=list(ALLOWED_USER_IDS)
            )
        else:
            generate_weekly_report()

    if schedule_day == "monday":
        schedule.every().monday.at(schedule_hour).do(scheduled_weekly_report)
    elif schedule_day == "tuesday":
        schedule.every().tuesday.at(schedule_hour).do(scheduled_weekly_report)
    elif schedule_day == "wednesday":
        schedule.every().wednesday.at(schedule_hour).do(scheduled_weekly_report)
    elif schedule_day == "thursday":
        schedule.every().thursday.at(schedule_hour).do(scheduled_weekly_report)
    elif schedule_day == "friday":
        schedule.every().friday.at(schedule_hour).do(scheduled_weekly_report)
    elif schedule_day == "saturday":
        schedule.every().saturday.at(schedule_hour).do(scheduled_weekly_report)
    else:  # 默认周日
        schedule.every().sunday.at(schedule_hour).do(scheduled_weekly_report)

    logger.info(f"已安排周报生成任务：每{WEEKLY_REPORT_DAY} {schedule_hour}")


def run_scheduler():
    """运行定时任务"""
    while not should_exit:
        try:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
        except Exception as e:
            logger.error(f"定时任务执行错误：{e}")
            time.sleep(300)  # 出错后等待 5 分钟再继续


def check_connection():
    """定期检查并维护连接，集成消息队列处理"""
    global should_exit, _reconnection_manager

    while not should_exit:
        try:
            # 如果有重连管理器，使用它来检查连接和恢复消息
            if _reconnection_manager:
                # 获取消息处理器字典
                message_handlers = _get_message_handlers()
                _reconnection_manager.check_connection_and_recover(message_handlers)
            else:
                # 原有的连接检查逻辑
                test_result = test_connectivity()
                if not test_result:
                    logger.warning("检测到连接问题，尝试重新配置代理...")
                    # 重新配置代理
                    configure_proxy_for_telegram()
        except Exception as e:
            logger.error(f"连接检查时出错：{e}")

        # 等待下次检查
        time.sleep(connection_check_interval)


def _get_message_handlers():
    """获取消息处理器字典，用于消息队列处理"""
    # 这里需要根据实际的处理器来配置
    # 由于原代码使用 dispatcher，我们需要从中提取处理器
    if _updater and _updater.dispatcher:
        from services.telegram_service.handlers.message_handlers import process_message
        from services.telegram_service.handlers.command_handlers import start, help_command

        return {
            'message': process_message,
            'callback_query': None,  # 如果有回调查询处理器，在这里添加
            'inline_query': None,    # 如果有内联查询处理器，在这里添加
        }
    return {}


def signal_handler(sig, frame):
    """处理进程信号，优雅退出"""
    global should_exit
    logger.info("接收到中断信号，准备停止机器人...")
    should_exit = True


def main():
    """主函数，启动机器人"""
    global _updater, _offset_manager, _queue_processor, _reconnection_manager
    logger.info("启动 TG-Notion 机器人...")

    # 加载环境变量
    load_dotenv()

    # 确认配置
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("错误：未设置 Telegram 机器人令牌")
        return 1

    if not ALLOWED_USER_IDS:
        logger.warning("警告：未设置允许的用户 ID，任何人都可以访问机器人")

    # 获取环境变量中的 SSL 证书验证设置
    disable_ssl_verify = os.environ.get(
        "DISABLE_TELEGRAM_SSL_VERIFY", "False"
    ).lower() in ("true", "1", "t", "yes")

    if disable_ssl_verify:
        logger.warning("警告：SSL 证书验证已禁用。这可能会导致安全风险。")

    # 初始化机器人
    updater = init_bot(token, disable_certificate_verification=disable_ssl_verify)

    if not updater:
        logger.error("无法初始化机器人，程序将退出")
        return 1

    # 注册命令处理程序
    updater = setup_telegram_bot(updater)

    # 保存到全局变量，供定时任务使用
    _updater = updater

    # 初始化消息队列组件
    try:
        logger.info("初始化消息队列处理组件...")
        _offset_manager = MessageOffsetManager()
        _queue_processor = MessageQueueProcessor(updater.bot, _offset_manager)
        _reconnection_manager = ReconnectionManager(updater.bot, _queue_processor)

        # 启动时处理一次积压消息（如果有的话）
        logger.info("检查并处理启动时的积压消息...")
        message_handlers = _get_message_handlers()
        processed, failed = _queue_processor.process_backlog_messages(message_handlers)
        if processed > 0 or failed > 0:
            logger.info(f"启动时处理积压消息完成，成功: {processed}, 失败: {failed}")

        # 清理旧记录
        _offset_manager.cleanup_old_records()

        logger.info("消息队列处理组件初始化完成")
    except Exception as e:
        logger.error(f"初始化消息队列组件失败: {e}")
        # 即使消息队列初始化失败，也继续启动机器人
        _offset_manager = None
        _queue_processor = None
        _reconnection_manager = None

    # 设置定时任务
    schedule_weekly_report()

    # 在单独的线程中运行调度器
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # 启动连接检查线程
    if KEEP_ALIVE:
        logger.info("启动连接保活线程...")
        connection_thread = threading.Thread(target=check_connection)
        connection_thread.daemon = True
        connection_thread.start()

    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动机器人
    try:
        logger.info("启动机器人轮询...")

        # 使用更优的轮询参数
        # 注意：如果启用了消息队列处理，我们不应该 drop_pending_updates
        drop_pending = _offset_manager is None  # 只有在消息队列未启用时才丢弃待处理更新

        updater.start_polling(
            timeout=30,  # 长轮询连接超时秒数
            drop_pending_updates=drop_pending,  # 根据消息队列状态决定是否删除待处理更新
            allowed_updates=[
                "message",
                "callback_query",
                "chat_member",
                "inline_query",
            ],  # 仅接收这些类型的更新
            bootstrap_retries=5,  # 重试连接次数
        )

        logger.info("机器人已成功启动，正在监听消息")
        # 等待，直到收到停止信号
        updater.idle()
    except Exception as e:
        logger.error(f"启动机器人时发生错误：{e}", exc_info=True)
        return 1

    logger.info("机器人已停止")
    return 0


# 启动程序
if __name__ == "__main__":
    sys.exit(main())
