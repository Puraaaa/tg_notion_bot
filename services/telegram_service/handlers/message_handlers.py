import logging

from telegram import Update
from telegram.ext import CallbackContext

from config import ALLOWED_USER_IDS
from services.gemini_service import analyze_content
from services.notion_service.utils import extract_hashtags, remove_hashtags_from_text, merge_tags
from utils.helpers import is_url_only
from utils.text_formatter import (
    extract_urls_from_entities,
    parse_message_entities,
)

from .pdf_handlers import handle_pdf_document
from .test_handlers import handle_test_message
from .todo_handlers import handle_todo_message

# 导入处理器
from .url_handlers import handle_multiple_urls_message, handle_url_message

# 配置日志
logger = logging.getLogger(__name__)


def process_message(update: Update, context: CallbackContext) -> None:
    """处理收到的消息"""
    if update.effective_user.id not in ALLOWED_USER_IDS:
        return

    message = update.message
    text = None
    entities = None
    contains_photo = message.photo and len(message.photo) > 0

    # 获取文本内容和实体，区分普通文本和带标题的媒体消息
    if message.text:
        text = message.text
        entities = message.entities
    elif message.caption:
        text = message.caption
        entities = message.caption_entities
    else:
        text = ""
        entities = []

    # 处理消息实体，提取格式化信息
    parsed_content = parse_message_entities(text, entities)

    # 从原始文本中提取 hashtag 标签
    original_hashtags = extract_hashtags(parsed_content["text"])
    
    # 从文本中移除 hashtag 标签，得到用于分析的清洁文本
    cleaned_text = remove_hashtags_from_text(parsed_content["text"])
    
    # 如果移除标签后文本为空或过短，保留原文本进行处理
    if not cleaned_text.strip() or len(cleaned_text.strip()) < 10:
        content_for_analysis = parsed_content["text"]
        content_for_storage = parsed_content["text"]
    else:
        content_for_analysis = cleaned_text
        content_for_storage = parsed_content["text"]  # 保存时使用原始文本（包含标签）

    # 获取创建时间
    created_at = message.date

    # 如果消息包含图片，添加前缀
    if contains_photo:
        logger.info(
            f"接收到包含图片的消息，用户 ID: {update.effective_user.id}，将只处理文字部分"
        )

        # 如果图片消息没有文字说明
        if not text:
            update.message.reply_text(
                "⚠️ 收到图片但没有文字说明。请添加说明后重新发送，或者单独发送要保存的文字内容。",
                parse_mode=None,  # 禁用 Markdown 解析
            )
            return

        # 给原始内容添加前缀，表明它来自包含图片的消息
        content_for_storage = f"[此内容来自包含图片的消息] {content_for_storage}"
        logger.info(f"处理图片消息的文字内容，长度：{len(content_for_storage)} 字符")

    # 提取所有 URL（从实体和文本）
    urls = extract_urls_from_entities(text, entities)

    # 检查特殊标签（从原始标签中检查）
    if "test" in original_hashtags:
        handle_test_message(update, parsed_content)
        return

    if "todo" in original_hashtags:
        handle_todo_message(update, content_for_storage, created_at)
        return

    # 检查是否是纯 URL 消息（使用清洁文本检查）
    if urls and is_url_only(cleaned_text if cleaned_text.strip() else content_for_storage):
        handle_url_message(update, urls[0], created_at)
        return

    # 多 URL 处理
    if len(urls) > 1:
        handle_multiple_urls_message(update, content_for_storage, urls, created_at)
        return
    elif len(urls) == 1:
        url = urls[0]
    else:
        url = ""

    # 短内容处理：如果内容不是纯 URL 且少于 200 字符，直接将内容作为摘要
    if len(content_for_analysis) < 200:
        # 通知用户正在处理消息
        processing_msg = (
            "正在处理消息..." if not contains_photo else "正在处理图片消息的文字内容..."
        )
        update.message.reply_text(processing_msg, parse_mode=None)  # 禁用 Markdown 解析

        # 仍需使用 Gemini API 分析提取标签
        analysis_result = analyze_content(content_for_analysis)
        
        # 合并原始标签和 AI 标签
        merged_tags = merge_tags(original_hashtags, analysis_result["tags"])
        
        # 存入 Notion，但使用原始内容作为摘要
        try:
            from services.notion_service import add_to_notion

            # 注意：此处传递的 content 只包含文本，不包含任何图片数据
            result = add_to_notion(
                content=content_for_storage,  # 保存包含标签的原始内容
                summary=cleaned_text if cleaned_text.strip() else content_for_storage,  # 摘要使用清洁文本
                tags=merged_tags,  # 使用合并后的标签
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
            logger.error(f"添加到 Notion 时出错：{e}")
            update.message.reply_text(
                f"⚠️ 保存到 Notion 时出错：{str(e)}",
                parse_mode=None,  # 禁用 Markdown 解析
            )
        return

    # 长内容处理：通知用户正在处理
    processing_msg = (
        "正在处理较长消息，这可能需要一点时间..."
        if not contains_photo
        else "正在处理图片消息中的较长文字内容，这可能需要一点时间..."
    )
    update.message.reply_text(processing_msg, parse_mode=None)  # 禁用 Markdown 解析

    # 使用 Gemini API 完整分析内容（使用清洁文本）
    analysis_result = analyze_content(content_for_analysis)
    
    # 合并原始标签和 AI 标签
    merged_tags = merge_tags(original_hashtags, analysis_result["tags"])

    # 存入 Notion
    try:
        from services.notion_service import add_to_notion

        result = add_to_notion(
            content=content_for_storage,  # 保存包含标签的原始内容
            summary=analysis_result["summary"],
            tags=merged_tags,  # 使用合并后的标签
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
        logger.error(f"添加到 Notion 时出错：{e}")
        update.message.reply_text(
            f"⚠️ 保存到 Notion 时出错：{str(e)}",
            parse_mode=None,  # 禁用 Markdown 解析
        )


def process_document(update: Update, context: CallbackContext) -> None:
    """处理文档文件，特别是 PDF"""
    if update.effective_user.id not in ALLOWED_USER_IDS:
        return

    message = update.message

    # 检查是否是 PDF 文件
    if message.document.file_name.lower().endswith(".pdf"):
        handle_pdf_document(update, context)
    else:
        # 对于非 PDF 文件，使用常规处理
        process_message(update, context)
