"""Notion File Upload API 实现

基于 Notion File Upload API，实现图片上传到 Notion 的功能。
流程：
1. POST /v1/file_uploads 获取 upload_url 和 file_upload_id
2. POST 到 upload_url 上传实际文件
3. 返回 file_upload_id 供创建页面时使用
"""

import logging
import os
from typing import Optional

import requests
import urllib3

from config import NOTION_TOKEN

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def get_proxy_settings():
    """获取代理设置"""
    proxy_url = (
        os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or os.environ.get("all_proxy")
    )
    if proxy_url:
        return {
            "http": proxy_url,
            "https": proxy_url,
        }
    return None


def get_notion_headers():
    """获取 Notion API 请求头"""
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
    }


def create_file_upload() -> Optional[dict]:
    """
    第一步：创建文件上传请求，获取 upload_url 和 file_upload_id

    返回：
        dict: 包含 upload_url 和 id 的字典
        None: 如果请求失败
    """
    url = f"{NOTION_API_BASE}/file_uploads"
    headers = get_notion_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = requests.post(
            url, headers=headers, json={},
            proxies=get_proxy_settings(), verify=False
        )
        response.raise_for_status()

        data = response.json()
        logger.info(f"成功创建文件上传请求，file_upload_id: {data.get('id')}")
        return {
            "upload_url": data.get("upload_url"),
            "id": data.get("id")
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"创建文件上传请求失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"响应内容: {e.response.text}")
        return None


def upload_file_to_notion(upload_url: str, file_path: str, filename: str = None) -> bool:
    """
    第二步：上传文件到 Notion

    参数：
        upload_url: 从第一步获取的上传 URL
        file_path: 本地文件路径
        filename: 文件名（可选，默认使用 file_path 的文件名）

    返回：
        bool: 是否上传成功
    """
    if not filename:
        filename = os.path.basename(file_path)

    headers = get_notion_headers()

    try:
        with open(file_path, 'rb') as f:
            files = {
                'file': (filename, f)
            }
            response = requests.post(
                upload_url, headers=headers, files=files,
                proxies=get_proxy_settings(), verify=False
            )
            response.raise_for_status()

        logger.info(f"成功上传文件: {filename}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"上传文件失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"响应内容: {e.response.text}")
        return False
    except FileNotFoundError:
        logger.error(f"文件不存在: {file_path}")
        return False


def upload_file_bytes_to_notion(upload_url: str, file_bytes: bytes, filename: str) -> bool:
    """
    第二步（替代版本）：直接上传字节数据到 Notion

    参数：
        upload_url: 从第一步获取的上传 URL
        file_bytes: 文件的字节数据
        filename: 文件名

    返回：
        bool: 是否上传成功
    """
    headers = get_notion_headers()

    try:
        files = {
            'file': (filename, file_bytes)
        }
        response = requests.post(
            upload_url, headers=headers, files=files,
            proxies=get_proxy_settings(), verify=False
        )
        response.raise_for_status()

        logger.info(f"成功上传文件: {filename}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"上传文件失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"响应内容: {e.response.text}")
        return False


def upload_image_to_notion(file_path: str = None, file_bytes: bytes = None, filename: str = None) -> Optional[str]:
    """
    完整流程：上传图片到 Notion 并返回 file_upload_id

    参数：
        file_path: 本地文件路径（与 file_bytes 二选一）
        file_bytes: 文件的字节数据（与 file_path 二选一）
        filename: 文件名（如果使用 file_bytes，则必须提供）

    返回：
        str: file_upload_id，可用于创建页面时引用
        None: 如果上传失败
    """
    if not file_path and not file_bytes:
        logger.error("必须提供 file_path 或 file_bytes")
        return None

    if file_bytes and not filename:
        logger.error("使用 file_bytes 时必须提供 filename")
        return None

    # 第一步：创建上传请求
    upload_info = create_file_upload()
    if not upload_info:
        return None

    upload_url = upload_info["upload_url"]
    file_upload_id = upload_info["id"]

    # 第二步：上传文件
    if file_path:
        success = upload_file_to_notion(upload_url, file_path, filename)
    else:
        success = upload_file_bytes_to_notion(upload_url, file_bytes, filename)

    if success:
        return file_upload_id
    return None


def create_file_property_value(file_upload_ids: list) -> dict:
    """
    创建文件属性值，用于 Notion 页面的 "文件和媒体" 属性

    参数：
        file_upload_ids: file_upload_id 列表

    返回：
        dict: Notion files 属性值对象
    """
    files = []
    for file_id in file_upload_ids:
        files.append({
            "type": "file_upload",
            "file_upload": {
                "id": file_id
            },
            "name": f"image_{file_id[:8]}.png"
        })

    return {"files": files}


def create_image_block(file_upload_id: str) -> dict:
    """
    创建图片块，用于添加到 Notion 页面内容

    参数：
        file_upload_id: 从 upload_image_to_notion 获取的 ID

    返回：
        dict: Notion 图片块对象
    """
    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "file_upload",
            "file_upload": {
                "id": file_upload_id
            }
        }
    }


def upload_multiple_images(images: list) -> list:
    """
    批量上传多张图片

    参数：
        images: 图片列表，每个元素是 dict，包含：
            - file_path: 本地文件路径（可选）
            - file_bytes: 文件字节数据（可选）
            - filename: 文件名

    返回：
        list: 成功上传的 file_upload_id 列表
    """
    file_upload_ids = []

    for img in images:
        file_upload_id = upload_image_to_notion(
            file_path=img.get("file_path"),
            file_bytes=img.get("file_bytes"),
            filename=img.get("filename")
        )
        if file_upload_id:
            file_upload_ids.append(file_upload_id)

    logger.info(f"批量上传完成，成功 {len(file_upload_ids)}/{len(images)} 张图片")
    return file_upload_ids
