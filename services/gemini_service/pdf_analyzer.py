"""
PDF 分析模块

提供 PDF 文档分析功能，支持提取内容、分析论文等操作
"""

import hashlib
import json
import logging
import os
import re

from config.prompts import NEW_PDF_ANALYSIS_PROMPT, NEW_PDF_TEXT_ANALYSIS_PROMPT
from utils.gemini_cache import get_from_cache, save_to_cache

from .client import GEMINI_AVAILABLE, model, vision_model

logger = logging.getLogger(__name__)


def analyze_pdf_content(pdf_path, url=None):
    """
    分析 PDF 文件内容，特别是学术论文

    参数：
    pdf_path (str): PDF 文件路径
    url (str, optional): PDF 原始 URL

    返回：
    dict: 包含论文分析的字典
    """
    if not GEMINI_AVAILABLE:
        logger.warning("Gemini API 未配置或不可用，无法解析 PDF")
        return None

    try:
        # 计算文件哈希作为缓存键
        file_hash = calculate_file_hash(pdf_path)
        cached_result = get_from_cache(file_hash, "pdf_analysis")

        if cached_result:
            logger.info(f"使用缓存的 PDF 分析结果：{os.path.basename(pdf_path)}")
            return cached_result

        # 检查文件大小 - Gemini 有输入限制
        file_size = os.path.getsize(pdf_path)
        if file_size > 20 * 1024 * 1024:  # 20MB
            logger.warning(
                f"PDF 文件过大 ({file_size / (1024 * 1024):.2f}MB)，超过 Gemini 处理限制"
            )
            return None

        # 尝试用 Gemini Vision API 处理 PDF
        try:
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()

            # 创建上下文提示
            url_context = f"该 PDF 文件来源：{url}" if url else "请分析以下 PDF 文件"
            prompt = NEW_PDF_ANALYSIS_PROMPT.format(url_context=url_context)

            # 创建包含 PDF 的请求
            image_parts = [{"mime_type": "application/pdf", "data": pdf_data}]

            # 发送请求到 Gemini
            logger.info("正在发送 PDF 到 Gemini 进行分析...")
            response = vision_model.generate_content([prompt, image_parts])

            # 处理响应文本，尝试提取 JSON
            response_text = response.text
            logger.info("收到 Gemini 响应，正在处理...")
            logger.debug(
                f"原始响应：{response_text[:500]}..."
            )  # 记录响应的前 500 个字符用于调试

            # 清理格式，移除可能的二进制数据
            response_text = response_text.replace("\\n", "\n").replace("\\", "")

            # 添加：调用从主服务模块导入的清理函数处理可能的二进制内容
            try:
                from services.gemini_service import clean_pdf_content

                response_text = clean_pdf_content(response_text)
                logger.info("已清理响应文本中的二进制数据")
            except ImportError:
                logger.warning("无法导入 clean_pdf_content 函数，跳过响应文本清理")

            # 尝试提取 JSON 格式的内容
            json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                try:
                    result = json.loads(json_str)
                except Exception as json_err:
                    logger.warning(f"JSON 块解析失败：{json_err}")
                    result = safe_extract_fields(response_text)
            else:
                # 尝试直接解析整个文本为 JSON
                try:
                    # 寻找可能的 JSON 部分
                    json_start = response_text.find("{")
                    json_end = response_text.rfind("}") + 1
                    if json_start >= 0 and json_end > json_start:
                        json_str = response_text[json_start:json_end]
                        result = json.loads(json_str)
                    else:
                        # 如果找不到完整的 JSON，使用正则表达式提取字段
                        result = safe_extract_fields(response_text)
                except json.JSONDecodeError:
                    # 使用字段提取方法
                    result = safe_extract_fields(response_text)

            # 确保有必要的字段
            required_fields = ["title", "brief_summary", "details", "insight"]
            for field in required_fields:
                if field not in result:
                    result[field] = ""

            # 缓存结果
            save_to_cache(file_hash, result, "pdf_analysis")

            return result

        except Exception as e:
            logger.error(f"使用 Gemini Vision API 分析 PDF {pdf_path} 时出错：{str(e)}")
            logger.debug(f"异常类型：{type(e).__name__}")
            logger.debug(f"异常详情：{e}")

            # 如果 Vision API 失败，尝试基于文本的方法
            return extract_and_analyze_pdf_text(pdf_path)

    except Exception as e:
        logger.error(f"分析 PDF {pdf_path} 内容时出错：{str(e)}")
        return {
            "title": "PDF 分析失败",
            "brief_summary": "无法解析 PDF 内容",
            "details": f"处理过程中出错：{str(e)}",
            "insight": "处理失败",
        }


def calculate_file_hash(file_path, block_size=8192):
    """
    计算文件的 MD5 哈希值

    参数：
        file_path: 文件路径
        block_size: 读取块大小

    返回：
        str: 文件的 MD5 哈希值
    """
    md5 = hashlib.md5()

    try:
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                md5.update(block)
        return md5.hexdigest()
    except Exception as e:
        logger.error(f"计算文件哈希失败：{e}")
        # 使用文件名和大小作为备用键
        try:
            return f"{os.path.basename(file_path)}_{os.path.getsize(file_path)}"
        except Exception:
            return os.path.basename(file_path)


def safe_extract_fields(text):
    """
    从文本中安全提取字段，处理非 JSON 格式的响应

    参数：
    text (str): 响应文本

    返回：
    dict: 提取的字段
    """
    result = {}

    # 使用更健壮的正则表达式提取字段
    title_pattern = r"(?:标题|title)[：:]\s*(.*?)(?:\n|$)"
    summary_pattern = (
        r"(?:简要摘要 | 摘要|brief_?summary)[：:]\s*(.*?)(?:\n\n|\n(?=[A-Z#])|$)"
    )
    insight_pattern = (
        r"(?:见解 | 评价 | 洞察|insight)[：:]\s*(.*?)(?:\n\n|\n(?=[A-Z#])|$)"
    )
    details_pattern = r"(?:详细分析 | 详情|details)[：:]\s*(.*?)(?:\n\n(?=[A-Z#])|$)"

    # 尝试匹配
    title_match = re.search(title_pattern, text, re.IGNORECASE | re.DOTALL)
    if title_match:
        result["title"] = title_match.group(1).strip()

    summary_match = re.search(summary_pattern, text, re.IGNORECASE | re.DOTALL)
    if summary_match:
        # 不需要在这里限制摘要长度，notion_service 会处理
        result["brief_summary"] = summary_match.group(1).strip()

    insight_match = re.search(insight_pattern, text, re.IGNORECASE | re.DOTALL)
    if insight_match:
        # 不需要在这里限制洞察内容长度，notion_service 会处理分割
        result["insight"] = insight_match.group(1).strip()

    details_match = re.search(details_pattern, text, re.IGNORECASE | re.DOTALL)
    if details_match:
        # 不限制详情长度，notion_service 会处理超长内容
        result["details"] = details_match.group(1).strip()

    # 如果没有找到详情字段，使用整个响应
    if "details" not in result or not result["details"]:
        result["details"] = text

    # 如果没有找到标题，使用默认标题
    if "title" not in result or not result["title"]:
        result["title"] = "PDF 分析结果"

    # 如果没有找到摘要，尝试使用前几行作为摘要
    if "brief_summary" not in result or not result["brief_summary"]:
        first_lines = " ".join(text.split("\n")[:3])
        result["brief_summary"] = first_lines  # 移除长度限制

    # 如果没有找到洞察，提供默认值
    if "insight" not in result or not result["insight"]:
        result["insight"] = "无法提取关键洞察"

    return result


def extract_and_analyze_pdf_text(pdf_path):
    """
    提取 PDF 文本并使用文本模型进行分析

    参数：
    pdf_path (str): PDF 文件路径

    返回：
    dict: 包含论文分析的字典
    """
    try:
        # 提取 PDF 文本内容
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        text = ""

        # 限制提取的页数，避免过长
        max_pages = min(20, len(reader.pages))

        for i in range(max_pages):
            page_text = reader.pages[i].extract_text()
            if page_text:  # 确保页面包含文本
                text += page_text + "\n\n"

        if not text.strip():
            logger.warning("PDF 未提取到文本，可能是扫描版或加密文件")
            return {
                "title": os.path.basename(pdf_path),
                "brief_summary": "无法提取文本内容，可能是扫描版 PDF 或加密文件",
                "details": "此 PDF 没有可提取的文本层",
                "insight": "无法分析",
            }

        # 限制文本长度
        text = text[:15000] + ("..." if len(text) > 15000 else "")

        # 使用文本模型生成分析
        prompt = NEW_PDF_TEXT_ANALYSIS_PROMPT.format(text=text)

        response = model.generate_content(prompt)
        response_text = response.text

        try:
            # 尝试解析为 JSON
            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                # 如果找不到 JSON，使用安全提取方法
                result = safe_extract_fields(response_text)

            # 确保有所有必要字段
            required_fields = ["title", "brief_summary", "details", "insight"]
            for field in required_fields:
                if field not in result:
                    result[field] = ""

            return result
        except Exception as json_err:
            logger.error(f"解析模型响应时出错：{json_err}")
            return safe_extract_fields(response_text)

    except Exception as e:
        # 更详细的错误日志，包括异常类型
        logger.error(f"提取和分析 PDF 文本时出错：{str(e)}")
        logger.debug(f"异常类型：{type(e).__name__}")

        # 尝试获取文件名作为标题
        try:
            filename = os.path.basename(pdf_path)
            title = os.path.splitext(filename)[0]
        except Exception:
            title = "PDF 文档"

        return {
            "title": title,
            "brief_summary": "无法提取或解析 PDF 文本",
            "details": f"在处理此 PDF 时发生错误：{type(e).__name__} - {str(e)}",
            "insight": "处理失败",
        }
