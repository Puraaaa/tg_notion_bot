import logging
from datetime import datetime
from typing import List, Optional

from services.gemini_service import generate_weekly_summary
from services.notion_service import create_weekly_report, get_weekly_entries

logger = logging.getLogger(__name__)


def generate_weekly_report(bot=None, chat_ids: Optional[List[int]] = None):
    """
    生成并发布每周报告

    参数：
        bot: Telegram Bot 实例，用于发送通知（可选）
        chat_ids: 要通知的用户 ID 列表（可选）

    返回：
        str: 创建的周报页面 URL
    """
    logger.info("开始生成每周报告")

    try:
        # 获取过去一周的条目
        entries = get_weekly_entries(days=7)
        logger.info(f"获取到 {len(entries)} 个条目")

        if not entries:
            logger.info("没有条目，跳过周报生成")
            _send_telegram_notification(
                bot, chat_ids, "⚠️ 本周没有内容，无法生成周报"
            )
            return None

        # 生成周报标题
        today = datetime.now()
        report_title = f"周报：{today.strftime('%Y-%m-%d')}"

        # 使用 Gemini 生成摘要
        report_content = generate_weekly_summary(entries)
        logger.info("成功生成周报内容")

        # 创建周报页面
        report_url = create_weekly_report(report_title, report_content)
        logger.info(f"成功创建周报：{report_url}")

        # 发送 Telegram 通知
        _send_telegram_notification(
            bot, chat_ids, f"✅ 周报已自动生成！\n\n📋 {report_title}\n🔗 {report_url}"
        )

        return report_url

    except Exception as e:
        logger.error(f"生成周报时出错：{e}")
        _send_telegram_notification(bot, chat_ids, f"⚠️ 自动生成周报时出错：{str(e)}")
        raise


def _send_telegram_notification(
    bot, chat_ids: Optional[List[int]], message: str
) -> None:
    """
    向指定用户发送 Telegram 通知

    参数：
        bot: Telegram Bot 实例
        chat_ids: 要通知的用户 ID 列表
        message: 通知消息内容
    """
    if bot is None or not chat_ids:
        return

    for chat_id in chat_ids:
        try:
            bot.send_message(chat_id=chat_id, text=message, parse_mode=None)
            logger.info(f"已向用户 {chat_id} 发送周报通知")
        except Exception as e:
            logger.error(f"向用户 {chat_id} 发送通知失败：{e}")
