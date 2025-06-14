import logging

from telegram import Update
from telegram.ext import CallbackContext

from config import ALLOWED_USER_IDS

# 配置日志
logger = logging.getLogger(__name__)


def start(update: Update, context: CallbackContext) -> None:
    """发送开始消息"""
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        update.message.reply_text("对不起，您没有权限使用此机器人。")
        return

    update.message.reply_text(
        "欢迎使用 TG-Notion 自动化机器人!\n"
        "您可以直接发送消息、链接或文件，机器人会将其保存到 Notion 数据库。\n"
        "\n"
        "特殊功能:\n"
        "- 发送纯 URL 会自动解析网页内容\n"
        "- 发送 PDF 文件会解析论文内容\n"
        "- 使用 #todo 标签可将任务添加到待办事项\n"
        "\n"
        "Zotero 功能:\n"
        "- /collections - 列出所有收藏集\n"
        "- /sync_papers - 同步最新论文\n"
        "- /sync_days - 同步近期论文\n"
        "\n"
        "输入 /help 查看详细使用说明",
        parse_mode=None,  # 禁用 Markdown 解析
    )


def help_command(update: Update, context: CallbackContext) -> None:
    """发送帮助信息"""
    if update.effective_user.id not in ALLOWED_USER_IDS:
        return

    update.message.reply_text(
        "使用指南:\n"
        "1. 直接发送任何消息，机器人会自动处理并保存到 Notion\n"
        "2. 发送纯链接时会自动提取网页内容并分析\n"
        "3. 发送 PDF 文件会进行论文解析并存入专用数据库\n"
        "4. 在消息中使用 #todo 标签将任务添加到待办事项列表\n"
        "5. 使用 #test 标签可以测试机器人，直接回显原始消息\n"
        "6. 在消息中添加 #标签名 会自动提取并与AI生成的标签合并保存\n"
        "7. 内容会被 AI 自动分析并生成摘要和标签\n"
        "8. 每周自动生成周报总结\n"
        "\n"
        "标签功能:\n"
        "- 支持中英文标签，如 #工作、#学习、#idea 等\n"
        "- 原始标签会与AI分析的标签合并，原始标签优先\n"
        "- 标签会从分析的内容中移除，保持摘要的清洁\n"
        "\n"
        "Zotero 相关命令:\n"
        "- /collections - 列出所有 Zotero 收藏集\n"
        "- /sync_papers [收藏集 ID] [数量] - 同步最近添加的指定数量论文\n"
        "- /sync_days [收藏集 ID] [天数] - 同步指定天数内添加的所有论文\n"
        "\n"
        "其他命令:\n"
        "- /start - 显示欢迎信息\n"
        "- /help - 显示此帮助信息\n"
        "- /weekly - 手动触发生成本周周报",
        parse_mode=None,  # 禁用 Markdown 解析
    )


def weekly_report_command(update: Update, context: CallbackContext) -> None:
    """手动触发生成周报"""
    if update.effective_user.id not in ALLOWED_USER_IDS:
        return

    from services.weekly_report import generate_weekly_report

    update.message.reply_text(
        "正在生成本周周报，请稍候...", parse_mode=None
    )  # 禁用 Markdown 解析

    try:
        report_url = generate_weekly_report()
        if report_url:
            update.message.reply_text(
                f"✅ 周报已生成！查看链接：{report_url}", parse_mode=None
            )  # 禁用 Markdown 解析
        else:
            update.message.reply_text(
                "⚠️ 本周没有内容，无法生成周报", parse_mode=None
            )  # 禁用 Markdown 解析
    except Exception as e:
        logger.error(f"生成周报时出错：{e}")
        update.message.reply_text(
            f"⚠️ 生成周报时出错：{str(e)}", parse_mode=None
        )  # 禁用 Markdown 解析
