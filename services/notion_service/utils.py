import logging
import os
import re
import tempfile
from datetime import datetime
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


def truncate_text(text, max_length=100):
    """截断文本至指定长度"""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def extract_url_from_text(text):
    """
    从文本中提取第一个 URL

    参数：
    text (str): 要分析的文本

    返回：
    str: 提取的 URL 或空字符串
    """
    urls = extract_all_urls_from_text(text)
    return urls[0] if urls else ""


def extract_all_urls_from_text(text):
    """
    从文本中提取所有 URL

    参数：
    text (str): 要分析的文本

    返回：
    list: 提取的 URL 列表
    """
    if not text:
        return []

    # 增强的 URL 正则表达式，能识别括号包裹的 URL 和标准 URL
    # 先匹配标准 URL 格式
    standard_url_pattern = (
        r'(?:https?://|www\.)[^\s\)\]\'"]+(?:\.[^\s\)\]\'"]+)+[^\s\)\]\'".,;:]+'
    )
    # 匹配括号中的 URL 格式 - 专门处理 (http://example.com) 这种情况
    bracketed_url_pattern = r"\((?:https?://|www\.)[^\s\)]+\)"

    # 查找所有标准 URL
    standard_urls = re.findall(standard_url_pattern, text)

    # 查找所有括号包裹的 URL 并去除括号
    bracketed_urls_with_brackets = re.findall(bracketed_url_pattern, text)
    bracketed_urls = [
        url[1:-1] for url in bracketed_urls_with_brackets
    ]  # 移除首尾的括号

    # 合并并去重
    all_urls = []
    for url in standard_urls + bracketed_urls:
        if url not in all_urls:
            all_urls.append(url)

    return all_urls


def format_datetime(dt):
    """格式化日期时间"""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def is_url_only(text):
    """检查文本是否只包含 URL"""
    if not text:
        return False

    # 清理文本中的空白字符
    cleaned_text = text.strip()

    # 检查是否只有一个 URL
    urls = extract_all_urls_from_text(cleaned_text)
    if len(urls) == 1 and urls[0].strip() == cleaned_text:
        return True

    return False


def download_file(url, file_extension=None):
    """从 URL 下载文件到临时位置

    参数：
    url (str): 文件 URL
    file_extension (str, optional): 文件扩展名，如'.pdf'

    返回：
    tuple: (本地文件路径，文件大小) 或 (None, 0)
    """
    try:
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code == 200:
            # 获取文件大小
            file_size = int(response.headers.get("content-length", 0))

            # 确定文件扩展名
            if not file_extension:
                # 尝试从 URL 中获取扩展名
                parsed_url = urlparse(url)
                path = parsed_url.path
                ext = os.path.splitext(path)[1]
                if ext:
                    file_extension = ext
                else:
                    # 尝试从 Content-Type 获取扩展名
                    content_type = response.headers.get("content-type", "")
                    if "pdf" in content_type:
                        file_extension = ".pdf"
                    elif "image" in content_type:
                        file_extension = ".jpg"  # 默认图片扩展名
                    else:
                        file_extension = ""

            # 创建临时文件
            fd, temp_path = tempfile.mkstemp(suffix=file_extension)
            os.close(fd)

            # 写入文件内容
            with open(temp_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

            logger.info(f"文件已下载到：{temp_path}")
            return temp_path, file_size
        else:
            logger.error(f"下载失败，状态码：{response.status_code}")
            return None, 0
    except Exception as e:
        logger.error(f"下载文件时出错：{e}")
        return None, 0


def format_notion_text(text, formatting=None):
    """
    格式化文本以符合 Notion API 格式

    参数：
    text (str): 要格式化的文本
    formatting (dict, optional): 格式化选项，如 {"bold": True, "italic": False, "code": False}

    返回：
    dict: 格式化后的 Notion 文本对象
    """
    text_obj = {"text": {"content": text}}

    if formatting:
        for format_type, value in formatting.items():
            if value and format_type in [
                "bold",
                "italic",
                "strikethrough",
                "underline",
                "code",
            ]:
                text_obj[format_type] = value

    return text_obj


def extract_tags_from_categories(content, categories):
    """
    从预定义类别中提取标签

    参数：
    content (str): 文本内容
    categories (list): 预定义类别列表

    返回：
    list: 匹配的类别列表
    """
    matched_categories = []
    content_lower = content.lower()

    for category in categories:
        # 简单匹配，实际应用中可能需要更复杂的匹配逻辑
        if category.lower() in content_lower:
            matched_categories.append(category)

    return matched_categories


def extract_hashtags(text):
    """
    从文本中提取所有 hashtag 标签

    参数：
    text (str): 要分析的文本

    返回：
    list: 提取的标签列表（不包含 # 符号）
    """
    if not text:
        return []

    # 匹配以 # 开头的标签，支持中英文、数字和下划线
    # 标签必须以字母、中文或数字开头，可以包含字母、中文、数字、下划线和连字符
    hashtag_pattern = r'#([a-zA-Z0-9\u4e00-\u9fff][a-zA-Z0-9\u4e00-\u9fff_-]*)'

    # 查找所有匹配的标签
    hashtags = re.findall(hashtag_pattern, text)

    # 去重并返回
    unique_hashtags = []
    for tag in hashtags:
        if tag not in unique_hashtags:
            unique_hashtags.append(tag)

    logger.info(f"从文本中提取到 {len(unique_hashtags)} 个hashtag标签: {unique_hashtags}")
    return unique_hashtags


def remove_hashtags_from_text(text):
    """
    从文本中移除 hashtag 标签，保持文本的可读性

    参数：
    text (str): 原始文本

    返回：
    str: 移除标签后的文本
    """
    if not text:
        return text

    # 移除 hashtag 标签，但保留其他内容
    hashtag_pattern = r'#[a-zA-Z0-9\u4e00-\u9fff][a-zA-Z0-9\u4e00-\u9fff_-]*\s*'

    # 替换 hashtag 为空字符串
    cleaned_text = re.sub(hashtag_pattern, '', text)

    # 清理多余的空白字符
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()

    return cleaned_text


def merge_tags(original_tags, ai_tags):
    """
    合并原始标签和 AI 生成的标签，去重并保持原始标签优先

    参数：
    original_tags (list): 从文本中提取的原始标签
    ai_tags (list): AI 分析生成的标签

    返回：
    list: 合并后的标签列表
    """
    if not original_tags:
        original_tags = []
    if not ai_tags:
        ai_tags = []

    # 转换为小写进行比较，但保留原始大小写
    merged_tags = []
    seen_tags_lower = set()

    # 首先添加原始标签（优先级更高）
    for tag in original_tags:
        tag_lower = tag.lower()
        if tag_lower not in seen_tags_lower:
            merged_tags.append(tag)
            seen_tags_lower.add(tag_lower)

    # 然后添加 AI 标签（如果不重复）
    for tag in ai_tags:
        tag_lower = tag.lower()
        if tag_lower not in seen_tags_lower:
            merged_tags.append(tag)
            seen_tags_lower.add(tag_lower)

    logger.info(f"标签合并完成: 原始标签 {len(original_tags)} 个，AI标签 {len(ai_tags)} 个，合并后 {len(merged_tags)} 个")
    return merged_tags
