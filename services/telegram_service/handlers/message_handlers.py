import logging
import os
import tempfile
from typing import List

from telegram import Message, Update
from telegram.ext import CallbackContext

from config import ALLOWED_USER_IDS
from services.gemini_service import analyze_content
from services.notion_service.utils import extract_hashtags, remove_hashtags_from_text, merge_tags
from services.notion_service import upload_image_to_notion
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


def download_and_upload_photos(message, context) -> list:
    """
    下载 Telegram 消息中的图片并上传到 Notion

    参数：
        message: Telegram 消息对象
        context: Telegram 上下文对象

    返回：
        list: 成功上传的 file_upload_id 列表
    """
    file_upload_ids = []

    if not message.photo:
        return file_upload_ids

    # Telegram 返回多个分辨率的图片，最后一个是最高分辨率
    photo = message.photo[-1]

    try:
        # 下载图片
        file = context.bot.get_file(photo.file_id)
        temp_path = os.path.join(tempfile.gettempdir(), f"{photo.file_unique_id}.jpg")
        file.download(temp_path)

        try:
            # 上传图片到 Notion
            logger.info(f"开始上传图片到 Notion: {temp_path}")
            file_upload_id = upload_image_to_notion(file_path=temp_path)

            if file_upload_id:
                file_upload_ids.append(file_upload_id)
                logger.info(f"图片上传成功，file_upload_id: {file_upload_id}")
            else:
                logger.error("图片上传到 Notion 失败")

        finally:
            # 清理临时文件
            try:
                os.remove(temp_path)
            except OSError as file_error:
                logger.warning(f"无法删除临时文件：{file_error}")

    except Exception as e:
        logger.error(f"下载或上传图片时出错：{e}")

    return file_upload_ids


def download_and_upload_photos_batch(messages: List[Message], context: CallbackContext) -> list:
    """
    批量下载多条消息中的图片并上传到 Notion

    参数：
        messages: Telegram 消息对象列表（来自同一 media group）
        context: Telegram 上下文对象

    返回：
        list: 成功上传的 file_upload_id 列表，顺序与消息顺序一致
    """
    file_upload_ids = []

    for message in messages:
        if not message.photo:
            continue

        # Telegram 返回多个分辨率的图片，最后一个是最高分辨率
        photo = message.photo[-1]

        try:
            # 下载图片
            file = context.bot.get_file(photo.file_id)
            temp_path = os.path.join(tempfile.gettempdir(), f"{photo.file_unique_id}.jpg")
            file.download(temp_path)

            try:
                # 上传图片到 Notion
                logger.info(f"开始上传图片到 Notion: {temp_path}")
                file_upload_id = upload_image_to_notion(file_path=temp_path)

                if file_upload_id:
                    file_upload_ids.append(file_upload_id)
                    logger.info(f"图片上传成功，file_upload_id: {file_upload_id}")
                else:
                    logger.error("图片上传到 Notion 失败")

            finally:
                # 清理临时文件
                try:
                    os.remove(temp_path)
                except OSError as file_error:
                    logger.warning(f"无法删除临时文件：{file_error}")

        except Exception as e:
            logger.error(f"下载或上传图片时出错：{e}")

    return file_upload_ids


def process_message(update: Update, context: CallbackContext) -> None:
    """处理收到的消息"""
    if update.effective_user.id not in ALLOWED_USER_IDS:
        return

    message = update.message

    # 检测是否是 media group（多图消息）
    if message.media_group_id and message.photo:
        from ..media_group import get_collector
        collector = get_collector()
        if collector and collector.add_message(update, context):
            # 消息已加入收集器，等待统一处理
            logger.info(
                f"消息 {message.message_id} 加入 media group {message.media_group_id}"
            )
            return

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
            f"接收到包含图片的消息，用户 ID: {update.effective_user.id}，将处理图片和文字"
        )

        # 如果图片消息没有文字说明，使用默认说明
        if not text:
            text = "图片消息"
            content_for_storage = "图片消息"
            content_for_analysis = "用户分享的图片"
        else:
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
            "正在处理消息..." if not contains_photo else "正在处理图片消息..."
        )
        update.message.reply_text(processing_msg, parse_mode=None)  # 禁用 Markdown 解析

        # 如果有图片，先上传图片
        file_upload_ids = []
        if contains_photo:
            file_upload_ids = download_and_upload_photos(message, context)

        # 仍需使用 Gemini API 分析提取标签
        analysis_result = analyze_content(content_for_analysis)

        # 合并原始标签和 AI 标签
        merged_tags = merge_tags(original_hashtags, analysis_result["tags"])

        # 存入 Notion，但使用原始内容作为摘要
        try:
            from services.notion_service import add_to_notion

            result = add_to_notion(
                content=content_for_storage,  # 保存包含标签的原始内容
                summary=cleaned_text if cleaned_text.strip() else content_for_storage,  # 摘要使用清洁文本
                tags=merged_tags,  # 使用合并后的标签
                url=url,
                created_at=created_at,
                file_upload_ids=file_upload_ids if file_upload_ids else None,
            )

            # 构建回复消息
            reply_parts = ["✅ 已保存到 Notion"]
            if file_upload_ids:
                reply_parts.append(f"📷 已上传 {len(file_upload_ids)} 张图片")
            reply_parts.append(f"📄 {result['title']}")
            reply_parts.append(f"🔗 {result['url']}")

            update.message.reply_text(
                "\n".join(reply_parts),
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
        else "正在处理图片消息，这可能需要一点时间..."
    )
    update.message.reply_text(processing_msg, parse_mode=None)  # 禁用 Markdown 解析

    # 如果有图片，先上传图片
    file_upload_ids = []
    if contains_photo:
        file_upload_ids = download_and_upload_photos(message, context)

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
            file_upload_ids=file_upload_ids if file_upload_ids else None,
        )

        # 构建回复消息
        reply_parts = ["✅ 已保存到 Notion"]
        if file_upload_ids:
            reply_parts.append(f"📷 已上传 {len(file_upload_ids)} 张图片")
        reply_parts.append(f"📄 {result['title']}")
        reply_parts.append(f"🔗 {result['url']}")

        update.message.reply_text(
            "\n".join(reply_parts),
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


def process_media_group(messages: List[Message], update: Update, context: CallbackContext) -> None:
    """
    处理 media group（多图消息）

    参数：
        messages: 属于同一 media group 的所有消息列表，已按 message_id 排序
        update: 第一条消息的 update 对象（用于回复）
        context: Telegram 上下文对象
    """
    if not messages:
        logger.warning("process_media_group 收到空消息列表")
        return

    logger.info(f"开始处理 media group，共 {len(messages)} 张图片")

    # 获取第一条消息（通常包含 caption）
    first_message = messages[0]

    # 提取文本内容（caption 通常只在第一条消息中）
    text = ""
    entities = []
    for msg in messages:
        if msg.caption:
            text = msg.caption
            entities = msg.caption_entities or []
            break

    # 获取创建时间
    created_at = first_message.date

    # 通知用户正在处理
    try:
        context.bot.send_message(
            chat_id=first_message.chat_id,
            text=f"正在处理 {len(messages)} 张图片...",
            reply_to_message_id=first_message.message_id,
            parse_mode=None
        )
    except Exception as e:
        logger.warning(f"发送处理通知失败: {e}")

    # 批量上传所有图片
    file_upload_ids = download_and_upload_photos_batch(messages, context)
    logger.info(f"成功上传 {len(file_upload_ids)} 张图片")

    # 处理文本内容
    if text:
        parsed_content = parse_message_entities(text, entities)
        original_hashtags = extract_hashtags(parsed_content["text"])
        cleaned_text = remove_hashtags_from_text(parsed_content["text"])

        if not cleaned_text.strip() or len(cleaned_text.strip()) < 10:
            content_for_analysis = parsed_content["text"]
            content_for_storage = parsed_content["text"]
        else:
            content_for_analysis = cleaned_text
            content_for_storage = parsed_content["text"]

        # 给原始内容添加前缀
        content_for_storage = f"[此内容来自包含 {len(messages)} 张图片的消息] {content_for_storage}"
    else:
        # 没有文字说明
        content_for_storage = f"图片消息（{len(messages)} 张图片）"
        content_for_analysis = "用户分享的多张图片"
        original_hashtags = []
        cleaned_text = ""

    # 提取 URL
    urls = extract_urls_from_entities(text, entities) if text else []
    url = urls[0] if urls else ""

    # 使用 Gemini API 分析内容
    analysis_result = analyze_content(content_for_analysis)

    # 合并原始标签和 AI 标签
    merged_tags = merge_tags(original_hashtags, analysis_result["tags"])

    # 存入 Notion
    try:
        from services.notion_service import add_to_notion

        result = add_to_notion(
            content=content_for_storage,
            summary=cleaned_text if cleaned_text.strip() else content_for_storage,
            tags=merged_tags,
            url=url,
            created_at=created_at,
            file_upload_ids=file_upload_ids if file_upload_ids else None,
        )

        # 构建回复消息
        reply_parts = ["✅ 已保存到 Notion"]
        reply_parts.append(f"📷 已上传 {len(file_upload_ids)} 张图片")
        reply_parts.append(f"📄 {result['title']}")
        reply_parts.append(f"🔗 {result['url']}")

        context.bot.send_message(
            chat_id=first_message.chat_id,
            text="\n".join(reply_parts),
            reply_to_message_id=first_message.message_id,
            parse_mode=None
        )
    except Exception as e:
        logger.error(f"添加到 Notion 时出错：{e}")
        context.bot.send_message(
            chat_id=first_message.chat_id,
            text=f"⚠️ 保存到 Notion 时出错：{str(e)}",
            reply_to_message_id=first_message.message_id,
            parse_mode=None
        )
