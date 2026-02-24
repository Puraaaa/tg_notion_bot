"""
URL 内容提取服务

使用 Firecrawl 作为主要抓取方式，BeautifulSoup 作为降级方案
"""

import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse

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

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message="Field name.*shadows an attribute"
                )
                from firecrawl import FirecrawlApp

                _firecrawl_client = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
            logger.info("Firecrawl 客户端初始化成功")
        except ImportError:
            logger.warning("firecrawl-py 未安装，将使用 BeautifulSoup 降级方案")
        except Exception as e:
            logger.warning(
                f"Firecrawl 客户端初始化失败：{e}，将使用 BeautifulSoup 降级方案"
            )
    return _firecrawl_client


def _normalize_x_url_for_fetch(url: str) -> str:
    """
    将 x.com 链接转换为 fixupx.com，便于抓取解析。
    仅按 host 维度替换，保留 path/query/fragment，避免误伤 query 中的 x.com 文本。
    """
    if not url or not url.strip():
        return url

    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if host in ("x.com", "www.x.com"):
            new_url = urlunparse(
                (
                    parsed.scheme,
                    "fixupx.com",
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
            logger.info(f"x 链接已转换为 fixupx 抓取：{url} -> {new_url}")
            return new_url
    except Exception as e:
        logger.warning(f"x 链接转换失败，使用原 URL: {e}")

    return url


def _looks_like_x_wall_or_error(content: str) -> bool:
    """判断内容是否是 X 登录墙或错误页，而非真实推文内容。"""
    if not content:
        return True

    markers = [
        "Don’t miss what’s happening",
        "Don't miss what's happening",
        "People on X are the first to know",
        "Something went wrong, but don’t fret",
        "Something went wrong, but don't fret",
        "Some privacy related extensions may cause issues on x.com",
    ]
    return any(marker in content for marker in markers)


def _extract_fixupx_content(url: str) -> Optional[str]:
    """
    fixupx 专用提取逻辑：
    - 使用默认请求头，避免被当作浏览器访问重定向到 x.com 登录墙
    - 优先从 og:title / og:description 提取推文核心信息
    """
    try:
        response = requests.get(url, timeout=15, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        og_title = soup.find("meta", attrs={"property": "og:title"})
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        og_image = soup.find("meta", attrs={"property": "og:image"})
        title = og_title.get("content", "").strip() if og_title else ""
        desc = og_desc.get("content", "").strip() if og_desc else ""
        image_url = og_image.get("content", "").strip() if og_image else ""

        if not desc:
            if title or image_url:
                fallback_parts = []
                if title:
                    fallback_parts.append(f"# {title}")
                fallback_parts.append(
                    "该推文文本不可提取（可能为空文本、受限内容或平台策略限制）。"
                )
                if image_url:
                    fallback_parts.append(f"媒体链接：{image_url}")
                return "\n\n".join(fallback_parts)
            return None

        content = f"# {title}\n\n{desc}" if title else desc
        if _looks_like_x_wall_or_error(content):
            return None
        return content
    except Exception:
        return None


def extract_url_content_with_firecrawl(url: str) -> Optional[str]:
    """
    使用 Firecrawl 提取网页内容
    """
    client = _get_firecrawl_client()
    if not client:
        return None

    try:
        result = client.scrape_url(url, params={"formats": ["markdown"]})

        if isinstance(result, dict) and result.get("markdown"):
            content = result["markdown"]
            metadata = result.get("metadata", {})
            if metadata:
                title = metadata.get("title", "")
                if title and not content.startswith(f"# {title}"):
                    content = f"# {title}\n\n{content}"

            if _looks_like_x_wall_or_error(content):
                return None

            logger.info(f"Firecrawl 成功提取 URL 内容，长度：{len(content)} 字符")
            return content

        logger.warning(f"Firecrawl 返回结果中没有 markdown 内容：{url}")
        return None
    except Exception as e:
        logger.warning(f"Firecrawl 提取 URL 内容失败：{e}")
        return None


def extract_url_content_with_beautifulsoup(url: str) -> Optional[str]:
    """
    使用 BeautifulSoup 提取网页内容（降级方案）
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

        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        if response.encoding is None or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding

        soup = BeautifulSoup(
            response.content, "html.parser", from_encoding=response.encoding
        )
        title = soup.title.string if soup.title else ""

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
                attrs = {}
                if "." in selector:
                    tag, cls = selector.split(".")
                    attrs["class"] = cls
                elif "#" in selector:
                    tag, elem_id = selector.split("#")
                    attrs["id"] = elem_id
                element = soup.find(tag, attrs)
            else:
                element = soup.find(selector)
            if element:
                main_content = element
                break

        if not main_content:
            main_content = soup.body if soup.body else soup

        for element in main_content.find_all(
            [
                "script",
                "style",
                "nav",
                "footer",
                "header",
                "aside",
                "noscript",
                "iframe",
            ]
        ):
            element.extract()

        markdown_content = md(str(main_content), heading_style="ATX")
        formatted_content = f"# {title}\n\n{markdown_content}"

        if _looks_like_x_wall_or_error(formatted_content):
            return None

        logger.info(
            f"BeautifulSoup 成功提取 URL 内容，长度：{len(formatted_content)} 字符"
        )
        return formatted_content
    except Exception as e:
        logger.warning(f"BeautifulSoup 提取 URL 内容失败：{e}")
        return None


def extract_url_content(url: str) -> str:
    """
    从 URL 中提取网页内容并转换为 Markdown 格式
    """
    url = _normalize_x_url_for_fetch(url)

    parsed_host = (urlparse(url).netloc or "").lower()
    if parsed_host == "fixupx.com":
        fixupx_content = _extract_fixupx_content(url)
        if fixupx_content:
            return fixupx_content

    if FIRECRAWL_API_KEY:
        content = extract_url_content_with_firecrawl(url)
        if content:
            return content
        logger.info(f"Firecrawl 提取失败，降级到 BeautifulSoup: {url}")

    content = extract_url_content_with_beautifulsoup(url)
    if content:
        return content

    error_msg = f"无法提取 URL 内容：{url}"
    logger.error(error_msg)
    return error_msg
