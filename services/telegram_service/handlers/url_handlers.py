import logging

from telegram import Update

from services.gemini_service import analyze_content
from services.notion_service import add_to_notion, is_pdf_url
from services.url_service import extract_url_content
from utils.text_formatter import extract_urls_from_text

from .pdf_handlers import handle_pdf_url

# 配置日志
logger = logging.getLogger(__name__)


def extract_url_from_text(text):
    """
    从文本中提取 URL

    参数：
    text (str): 可能包含 URL 的文本

    返回：
    str: 提取的第一个 URL，如果没有找到则返回原始文本
    """
    urls = extract_urls_from_text(text)
    return urls[0] if urls else text


def handle_url_message(update: Update, url, created_at):
    """处理纯 URL 消息"""
    # 提取 URL
    url = extract_url_from_text(url)

    # 首先检查是否是 PDF URL
    if is_pdf_url(url):
        update.message.reply_text(
            "检测到 PDF 链接，正在下载并解析论文内容，请稍候...", parse_mode=None
        )  # 禁用 Markdown 解析
        handle_pdf_url(update, url, created_at)
        return

    update.message.reply_text(
        "正在解析 URL 内容，请稍候...", parse_mode=None
    )  # 禁用 Markdown 解析

    try:
        # 提取网页内容 - 现在不会截断内容
        content = extract_url_content(url)

        if not content:
            update.message.reply_text(
                "⚠️ 无法提取 URL 内容", parse_mode=None
            )  # 禁用 Markdown 解析
            return

        # 分析内容
        analysis_result = analyze_content(content)

        # 存入 Notion - add_to_notion 函数会在内容过长时自动使用分批处理
        result = add_to_notion(
            content=content,
            summary=analysis_result["summary"],
            tags=analysis_result["tags"],
            url=url,
            created_at=created_at,
        )

        update.message.reply_text(
            f"✅ 已保存到 Notion\n"
            f"📄 {result['title']}\n"
            f"🔗 {result['url']}",
            parse_mode=None
        )

    except Exception as e:
        logger.error(f"处理 URL 时出错：{e}")
        update.message.reply_text(
            f"⚠️ 处理 {url} 时出错：{str(e)}", parse_mode=None
        )  # 禁用 Markdown 解析


def handle_multiple_urls_message(update: Update, content, urls, created_at):
    """处理包含多个 URL 的消息"""
    # 处理可能在括号内的 URLs
    processed_urls = [extract_url_from_text(url) for url in urls]

    update.message.reply_text(
        f"检测到 {len(processed_urls)} 个链接，正在处理消息内容...",
        parse_mode=None,  # 禁用 Markdown 解析
    )

    # 创建一个包含原始消息和 URL 标记的文本
    rich_content = content

    # 使用 Gemini 直接分析原始消息内容，不访问 URL
    analysis_result = analyze_content(rich_content)

    # 存入 Notion，将 URLs 作为参考信息
    try:
        # 主要 URL 使用第一个链接
        primary_url = processed_urls[0] if processed_urls else ""

        # 创建 URL 列表作为附加信息
        url_list_content = "消息中包含的链接：\n"
        for i, url in enumerate(processed_urls, 1):
            url_list_content += f"{i}. {url}\n"

        # 合并原始内容和 URL 列表
        combined_content = f"{rich_content}\n\n{url_list_content}"

        # 创建 Notion 页面
        result = add_to_notion(
            content=combined_content,
            summary=analysis_result["summary"],
            tags=analysis_result["tags"],
            url=primary_url,  # 主 URL 使用第一个
            created_at=created_at,
        )

        # 返回成功消息
        update.message.reply_text(
            f"✅ 已保存到 Notion（包含 {len(processed_urls)} 个链接）\n"
            f"📄 {result['title']}\n"
            f"🔗 {result['url']}",
            parse_mode=None,
        )
    except Exception as e:
        logger.error(f"处理多 URL 消息时出错：{e}")
        update.message.reply_text(
            f"⚠️ 处理消息时出错：{str(e)}", parse_mode=None
        )  # 禁用 Markdown 解析
