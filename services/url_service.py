"""
URL 内容提取服务

使用 Firecrawl 作为主要抓取方式，BeautifulSoup 作为降级方案
"""
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from config import FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)

# Firecrawl 客户端（延迟初始化）
_firecrawl_client = None


def _get_firecrawl_client():
    """获取 Firecrawl 客户端实例"""
    global _firecrawl_client
    if _firecrawl_client is None and FIRECRAWL_API_KEY:
        try:
            import warnings
            # 忽略 pydantic 字段命名警告
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Field name.*shadows an attribute")
                from firecrawl import FirecrawlApp
                _firecrawl_client = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
            logger.info("Firecrawl 客户端初始化成功")
        except ImportError:
            logger.warning("firecrawl-py 未安装，将使用 BeautifulSoup 降级方案")
        except Exception as e:
            logger.warning(f"Firecrawl 客户端初始化失败: {e}，将使用 BeautifulSoup 降级方案")
    return _firecrawl_client


def extract_url_content_with_firecrawl(url: str) -> Optional[str]:
    """
    使用 Firecrawl 提取网页内容

    参数：
    url (str): 需要提取内容的 URL

    返回：
    str: 提取的 Markdown 格式内容，失败返回 None
    """
    client = _get_firecrawl_client()
    if not client:
        return None

    try:
        # 使用 Firecrawl 抓取页面（FirecrawlApp 使用 scrape_url 方法）
        result = client.scrape_url(url, params={"formats": ["markdown"]})

        # 提取 markdown 内容（FirecrawlApp 返回字典）
        if isinstance(result, dict) and result.get("markdown"):
            content = result["markdown"]
            # 如果有标题元数据，添加到内容开头
            metadata = result.get("metadata", {})
            if metadata:
                title = metadata.get("title", "")
                if title and not content.startswith(f"# {title}"):
                    content = f"# {title}\n\n{content}"
            logger.info(f"Firecrawl 成功提取 URL 内容，长度：{len(content)} 字符")
            return content

        logger.warning(f"Firecrawl 返回结果中没有 markdown 内容: {url}")
        return None

    except Exception as e:
        logger.warning(f"Firecrawl 提取 URL 内容失败: {e}")
        return None


def extract_url_content_with_beautifulsoup(url: str) -> Optional[str]:
    """
    使用 BeautifulSoup 提取网页内容（降级方案）

    参数：
    url (str): 需要提取内容的 URL

    返回：
    str: 提取并转换为 Markdown 格式的网页内容，失败返回 None
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        # 获取网页内容
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        # 修复编码问题：优先使用响应头中的编码，否则自动检测
        if response.encoding is None or response.encoding.lower() == 'iso-8859-1':
            # requests 默认使用 ISO-8859-1，需要从内容中检测真实编码
            response.encoding = response.apparent_encoding

        # 使用 BeautifulSoup 解析 HTML，指定 from_encoding 确保正确解码
        soup = BeautifulSoup(response.content, "html.parser", from_encoding=response.encoding)

        # 提取标题
        title = soup.title.string if soup.title else ""

        # 提取正文内容 - 首先尝试找到主要内容区域
        main_content = None
        for selector in [
            "article",
            "main",
            "div#content",
            "div.content",
            "div.post",
            "div.article",
            "div.post-content",
            "div.entry-content",
            "div.article-content",
            "body",
        ]:
            if selector.startswith("div"):
                # 处理带 class 或 id 的选择器
                attrs = {}
                if "." in selector:
                    tag, cls = selector.split(".")
                    attrs["class"] = cls
                elif "#" in selector:
                    tag, id = selector.split("#")
                    attrs["id"] = id
                element = soup.find(tag, attrs)
            else:
                element = soup.find(selector)

            if element:
                main_content = element
                break

        # 如果没找到主要内容区域，使用整个 body
        if not main_content:
            main_content = soup.body if soup.body else soup

        # 从内容中移除不需要的元素
        for element in main_content.find_all(
            ["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]
        ):
            element.extract()

        # 将 HTML 转换为 Markdown
        markdown_content = md(str(main_content), heading_style="ATX")

        # 格式化内容，确保标题在最前面
        formatted_content = f"# {title}\n\n{markdown_content}"

        logger.info(f"BeautifulSoup 成功提取 URL 内容，长度：{len(formatted_content)} 字符")
        return formatted_content

    except Exception as e:
        logger.warning(f"BeautifulSoup 提取 URL 内容失败: {e}")
        return None


def extract_url_content(url: str) -> str:
    """
    从 URL 中提取网页内容并转换为 Markdown 格式

    优先使用 Firecrawl，失败时降级到 BeautifulSoup

    参数：
    url (str): 需要提取内容的 URL

    返回：
    str: 提取并转换为 Markdown 格式的网页内容
    """
    # 首先尝试使用 Firecrawl
    if FIRECRAWL_API_KEY:
        content = extract_url_content_with_firecrawl(url)
        if content:
            return content
        logger.info(f"Firecrawl 提取失败，降级到 BeautifulSoup: {url}")

    # 降级到 BeautifulSoup
    content = extract_url_content_with_beautifulsoup(url)
    if content:
        return content

    # 两种方式都失败
    error_msg = f"无法提取 URL 内容：{url}"
    logger.error(error_msg)
    return error_msg
