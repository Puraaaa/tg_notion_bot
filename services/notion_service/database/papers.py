import logging
import os
import re
import tempfile
import time

import requests

from config import NOTION_PAPERS_DATABASE_ID

from ..client import notion

logger = logging.getLogger(__name__)

# 导入 Gemini 服务
# try:
#     from services.gemini_service import analyze_pdf_content

#     GEMINI_AVAILABLE = True
# except ImportError:
#     logger.warning("无法导入 Gemini 服务，将使用备用方法解析 PDF")
#     GEMINI_AVAILABLE = False

try:
    from services.gemini_service import clean_pdf_content

    CLEAN_PDF_AVAILABLE = True
except ImportError:
    logger.warning("无法导入 clean_pdf_content 函数，将使用内部方法清理 PDF 内容")
    CLEAN_PDF_AVAILABLE = False


def get_existing_dois():
    """
    从 Notion 论文数据库中获取所有已存在的 DOI

    返回：
    set: 已存在的 DOI 集合
    """
    if not NOTION_PAPERS_DATABASE_ID:
        logger.error("未设置论文数据库 ID")
        return set()

    try:
        # 检查数据库是否有 DOI 字段
        db_info = notion.databases.retrieve(database_id=NOTION_PAPERS_DATABASE_ID)
        if "DOI" not in db_info.get("properties", {}):
            logger.warning("论文数据库中没有 DOI 字段，无法检查重复")
            return set()

        # 查询所有条目
        existing_dois = set()
        start_cursor = None
        has_more = True

        while has_more:
            response = notion.databases.query(
                database_id=NOTION_PAPERS_DATABASE_ID,
                start_cursor=start_cursor,
                page_size=100,  # 每页最多获取 100 条
                filter={"property": "DOI", "rich_text": {"is_not_empty": True}},
            )

            # 提取 DOI
            for page in response["results"]:
                if "DOI" in page["properties"]:
                    rich_text = page["properties"]["DOI"].get("rich_text", [])
                    if rich_text and "plain_text" in rich_text[0]:
                        doi = rich_text[0]["plain_text"].strip().lower()
                        if doi:
                            existing_dois.add(doi)

            # 检查是否有更多数据
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

            if has_more:
                # 避免请求过于频繁
                time.sleep(0.5)

        logger.info(f"从 Notion 中获取到 {len(existing_dois)} 个已同步的 DOI")
        return existing_dois

    except Exception as e:
        logger.error(f"获取已存在的 DOI 时出错：{e}")
        return set()


def add_to_papers_database(
    title, analysis, created_at=None, pdf_url=None, metadata=None, zotero_id=None
):
    """将论文分析添加到论文数据库"""
    # 原函数内容
    pass


def add_paper_metadata_to_properties(properties, metadata):
    """
    将论文元数据添加到 Notion 属性中

    参数：
    properties (dict): 现有属性字典
    metadata (dict): 元数据字典

    返回：
    dict: 更新后的属性字典
    """
    # 添加作者（多选文本）
    if metadata.get("authors"):
        authors = metadata["authors"]
        if isinstance(authors, list) and authors:
            # 转为逗号分隔的字符串
            author_text = ", ".join(authors)
            properties["Authors"] = {
                "rich_text": [
                    {"text": {"content": author_text[:2000]}}
                ]  # Notion API 限制
            }

    # 添加期刊/出版物（文本）
    if metadata.get("publication"):
        properties["Publication"] = {
            "rich_text": [{"text": {"content": metadata["publication"][:2000]}}]
        }

    # 添加发布日期 - 改进日期解析
    if metadata.get("date"):
        try:
            # 尝试解析日期字符串
            from dateutil.parser import parse

            date_obj = parse(metadata["date"])
            properties["PublishDate"] = {
                "date": {"start": date_obj.strftime("%Y-%m-%d")}
            }
        except Exception:
            # 如果无法解析，使用原始字符串
            properties["PublishYear"] = {
                "rich_text": [{"text": {"content": metadata["date"][:100]}}]
            }

    # 添加 DOI
    if metadata.get("doi"):
        properties["DOI"] = {
            "rich_text": [{"text": {"content": metadata["doi"][:100]}}]
        }

    # 添加 Zotero 链接
    if metadata.get("zotero_link"):
        properties["ZoteroLink"] = {"url": metadata["zotero_link"]}

    # 添加 Zotero ID - 确保 ZoteroID 字段始终存在
    if metadata.get("zotero_id"):
        properties["ZoteroID"] = {
            "rich_text": [{"text": {"content": metadata["zotero_id"]}}]
        }

    # 添加标签（多选）- 确保所有标签都被正确处理
    if metadata.get("tags") and isinstance(metadata["tags"], list):
        multi_select_tags = []
        for tag in metadata["tags"][:20]:  # 增加标签数量限制
            if isinstance(tag, str):
                tag_name = tag
            elif isinstance(tag, dict) and "tag" in tag:
                tag_name = tag["tag"]
            else:
                continue

            # 确保标签名称有效且不超过长度限制
            if tag_name and len(tag_name) > 0:
                multi_select_tags.append({"name": tag_name[:100]})  # 限制长度

        if multi_select_tags:
            properties["Tags"] = {"multi_select": multi_select_tags}

    # 添加条目类型
    if metadata.get("item_type"):
        properties["ItemType"] = {
            "rich_text": [{"text": {"content": metadata.get("item_type")}}]
        }

    return properties


def ensure_papers_database_properties():
    """
    确保论文数据库拥有所需的所有属性/字段
    第一次使用时会初始化数据库结构
    """
    try:
        # 获取当前数据库结构
        db_info = notion.databases.retrieve(database_id=NOTION_PAPERS_DATABASE_ID)
        existing_properties = db_info.get("properties", {})

        # 检查并添加缺失的属性
        required_properties = {
            "Abstract": {"rich_text": {}},
            "Authors": {"rich_text": {}},
            "Publication": {"rich_text": {}},
            "PublishDate": {"date": {}},
            "PublishYear": {"rich_text": {}},  # 备用字段，当无法解析日期时使用
            "DOI": {"rich_text": {}},
            "Tags": {"multi_select": {}},
            "ZoteroLink": {"url": {}},
            "ZoteroID": {"rich_text": {}},
            "URL": {"url": {}},
            "ItemType": {"rich_text": {}},  # 添加条目类型属性
        }

        missing_properties = {}
        for prop_name, prop_config in required_properties.items():
            if prop_name not in existing_properties:
                missing_properties[prop_name] = prop_config

        # 如果有缺失的属性，更新数据库结构
        if missing_properties:
            logger.info(
                f"正在添加缺失的论文数据库属性：{', '.join(missing_properties.keys())}"
            )
            notion.databases.update(
                database_id=NOTION_PAPERS_DATABASE_ID, properties=missing_properties
            )
            logger.info("数据库结构已更新")

    except Exception as e:
        logger.warning(f"检查/更新数据库结构时出错：{e}")
        # 继续执行，因为这不是致命错误


def is_pdf_url(url):
    """
    检查 URL 是否为 PDF 文件链接

    参数：
    url (str): 要检查的 URL

    返回：
    bool: 如果 URL 指向 PDF 文件则返回 True，否则返回 False
    """
    # URL 路径以 .pdf 结尾
    if re.search(r"\.pdf(\?.*)?$", url, re.IGNORECASE):
        return True

    try:
        # 检查 HTTP 头中的内容类型
        head_response = requests.head(url, allow_redirects=True, timeout=5)
        content_type = head_response.headers.get("Content-Type", "")
        if "application/pdf" in content_type.lower():
            return True

        # 如果 HEAD 请求没有返回内容类型，尝试 GET 请求的前几个字节
        if "content-type" not in head_response.headers:
            response = requests.get(url, stream=True, timeout=5)
            # 读取前几个字节检查 PDF 魔数 %PDF-
            content_start = response.raw.read(5).decode("latin-1", errors="ignore")
            if content_start.startswith("%PDF-"):
                return True
            response.close()
    except Exception as e:
        logger.warning(f"检查 PDF URL 时出错：{e}")

    return False


def download_pdf(url):
    """
    从 URL 下载 PDF 文件到临时位置

    参数：
    url (str): PDF 文件的 URL

    返回：
    tuple: (下载的 PDF 文件路径，文件大小 (字节)), 下载失败则返回 (None, 0)
    """
    try:
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code == 200:
            # 获取文件大小
            file_size = int(response.headers.get("content-length", 0))
            logger.info(f"PDF 文件大小：{file_size / (1024 * 1024):.2f} MB")

            # 创建临时文件
            fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)

            # 将内容写入临时文件
            downloaded_size = 0
            with open(temp_path, "wb") as pdf_file:
                for chunk in response.iter_content(chunk_size=8192):
                    pdf_file.write(chunk)
                    downloaded_size += len(chunk)

            logger.info(f"PDF 文件已下载到：{temp_path}")

            # 验证 PDF 文件有效性
            if not is_valid_pdf(temp_path):
                logger.error(f"下载的文件不是有效的 PDF：{url}")
                os.remove(temp_path)
                return None, 0

            return temp_path, downloaded_size or file_size
        else:
            logger.error(f"下载 PDF 失败，状态码：{response.status_code}")
            return None, 0
    except Exception as e:
        logger.error(f"下载 PDF 时出错：{e}")
        return None, 0


def is_valid_pdf(file_path):
    """
    检查文件是否为有效的 PDF

    参数：
    file_path (str): PDF 文件路径

    返回：
    bool: 如果文件是有效的 PDF 则返回 True，否则返回 False
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(5).decode("latin-1", errors="ignore")
            # 检查 PDF 文件头部标识
            return header.startswith("%PDF-")
    except Exception as e:
        logger.error(f"检查 PDF 有效性时出错：{e}")
        return False


def process_pdf_content(content):
    """
    处理 PDF 内容，移除二进制垃圾数据

    参数：
    content (str): PDF 内容文本

    返回：
    str: 清理后的文本内容
    """
    if not content:
        return ""

    # 检测并移除 PDF 二进制尾部数据
    if "\r\ntrailer\r\n<<" in content:
        content = content.split("\r\ntrailer\r\n<<")[0]

    # 移除其他可能的二进制数据标记
    binary_markers = [
        "\r\nstartxref\r\n",
        "%%EOF",
        "\r\n\x00\x00",
        r"<</Size \d+/Root \d+",
    ]

    for marker in binary_markers:
        parts = re.split(marker, content, flags=re.IGNORECASE)
        if len(parts) > 1:
            content = parts[0]

    return content.strip()


def check_paper_exists_in_notion(doi: str = None, zotero_id: str = None) -> bool:
    """
    检查论文是否已存在于 Notion 数据库中

    参数：
        doi: 论文的 DOI（可选）
        zotero_id: 论文的 Zotero ID（可选）

    返回：
        bool: 如果论文已存在则返回 True，否则返回 False

    说明：
        先通过 DOI 检查，如果没有 DOI  or 未找到，则通过 ZoteroID 检查
    """
    try:
        # 保持对同一个 notion 客户端的引用
        global notion

        # 首先通过 DOI 检查（如果提供）
        if doi:
            response = notion.databases.query(
                database_id=NOTION_PAPERS_DATABASE_ID,
                filter={"property": "DOI", "rich_text": {"equals": doi}},
            )

            # 如果找到结果，则论文已存在
            if len(response.get("results", [])) > 0:
                logger.info(f"通过 DOI 找到已存在的论文记录：{doi}")
                return True

        # 如果 DOI 检查未找到结果，且提供了 ZoteroID，则通过 ZoteroID 检查
        if zotero_id:
            response = notion.databases.query(
                database_id=NOTION_PAPERS_DATABASE_ID,
                filter={"property": "ZoteroID", "rich_text": {"equals": zotero_id}},
            )

            # 如果找到结果，则论文已存在
            if len(response.get("results", [])) > 0:
                logger.info(f"通过 ZoteroID 找到已存在的论文记录：{zotero_id}")
                return True

        # 两种检查都未找到匹配项
        return False

    except Exception as e:
        logger.error(f"检查论文是否存在时出错：{e}")
        return False


def get_existing_zotero_ids():
    """
    从 Notion 论文数据库中获取所有已存在的 ZoteroID

    返回：
    set: 已存在的 ZoteroID 集合
    """
    if not NOTION_PAPERS_DATABASE_ID:
        logger.error("未设置论文数据库 ID")
        return set()

    try:
        # 检查数据库是否有 ZoteroID 字段
        db_info = notion.databases.retrieve(database_id=NOTION_PAPERS_DATABASE_ID)
        if "ZoteroID" not in db_info.get("properties", {}):
            logger.warning("论文数据库中没有 ZoteroID 字段，无法检查重复")
            return set()

        # 查询所有条目
        existing_zotero_ids = set()
        start_cursor = None
        has_more = True

        while has_more:
            response = notion.databases.query(
                database_id=NOTION_PAPERS_DATABASE_ID,
                start_cursor=start_cursor,
                page_size=100,  # 每页最多获取 100 条
                filter={"property": "ZoteroID", "rich_text": {"is_not_empty": True}},
            )

            # 提取 ZoteroID
            for page in response["results"]:
                if "ZoteroID" in page["properties"]:
                    rich_text = page["properties"]["ZoteroID"].get("rich_text", [])
                    if rich_text and "plain_text" in rich_text[0]:
                        zotero_id = rich_text[0]["plain_text"].strip().lower()
                        if zotero_id:
                            existing_zotero_ids.add(zotero_id)

            # 检查是否有更多数据
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

            if has_more:
                # 避免请求过于频繁
                time.sleep(0.5)

        logger.info(
            f"从 Notion 中获取到 {len(existing_zotero_ids)} 个已同步的 ZoteroID"
        )
        return existing_zotero_ids

    except Exception as e:
        logger.error(f"获取已存在的 ZoteroID 时出错：{e}")
        return set()


def prepare_metadata_for_notion(metadata):
    """
    从 Zotero 元数据准备 Notion 需要的元数据格式

    参数：
    metadata (dict): Zotero 元数据

    返回：
    dict: Notion 格式的元数据
    """
    notion_metadata = {}

    # 处理作者
    if metadata.get("authors"):
        notion_metadata["authors"] = metadata["authors"]
    elif metadata.get("creators"):
        authors = []
        for creator in metadata.get("creators", []):
            if creator.get("firstName") or creator.get("lastName"):
                author = f"{creator.get('firstName', '')} {creator.get('lastName', '')}".strip()
                authors.append(author)
        if authors:
            notion_metadata["authors"] = authors

    # 处理出版物信息
    if metadata.get("publication"):
        notion_metadata["publication"] = metadata.get("publication")

    # 处理日期
    if metadata.get("date"):
        notion_metadata["date"] = metadata.get("date")

    # 处理 DOI - 确保保存为小写以便一致性比较
    if metadata.get("doi"):
        notion_metadata["doi"] = metadata.get("doi", "").lower().strip()

    # 处理 Zotero 链接和 ID
    if metadata.get("zotero_id"):
        notion_metadata["zotero_link"] = (
            f"zotero://select/library/items/{metadata.get('zotero_id')}"
        )
        notion_metadata["zotero_id"] = metadata.get("zotero_id")

    # 处理标签
    if metadata.get("tags"):
        # 处理两种可能的标签格式
        if isinstance(metadata["tags"], list) and metadata["tags"]:
            # 如果标签是简单的字符串列表
            if isinstance(metadata["tags"][0], str):
                notion_metadata["tags"] = metadata["tags"]
            # 如果标签是对象列表（Zotero 标签通常是这种格式）
            elif isinstance(metadata["tags"][0], dict) and "tag" in metadata["tags"][0]:
                notion_metadata["tags"] = [
                    tag_obj.get("tag")
                    for tag_obj in metadata["tags"]
                    if tag_obj.get("tag")
                ]

    # 添加条目类型
    # if metadata.get('item_type'):
    #     notion_metadata['item_type'] = metadata['item_type']

    return notion_metadata


def extract_and_process_pdf_content(pdf_path):
    """
    从 PDF 文件提取并处理文本内容，移除二进制垃圾数据

    参数：
    pdf_path (str): PDF 文件路径

    返回：
    str: 处理后的文本内容
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf_path)
        content = ""

        # 限制处理页数避免过长
        max_pages = min(20, len(reader.pages))

        for i in range(max_pages):
            page_text = reader.pages[i].extract_text()
            if page_text:
                content += page_text + "\n\n"

        # 对提取的内容进行清理
        if not content.strip():
            return ""

        # 使用全局清理函数或内部处理函数
        if CLEAN_PDF_AVAILABLE:
            cleaned_content = clean_pdf_content(content)
        else:
            cleaned_content = process_pdf_content(content)

        logger.info(f"成功从 PDF 提取并清理了内容：{len(cleaned_content)} 字符")
        return cleaned_content

    except Exception as e:
        logger.error(f"提取处理 PDF 内容时出错：{e}")
        return ""
