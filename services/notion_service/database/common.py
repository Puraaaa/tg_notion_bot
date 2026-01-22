import logging
import time
from datetime import datetime, timedelta

import pytz

from config import NOTION_DATABASE_ID
from services.gemini_service import analyze_content
from utils.helpers import truncate_text

from ..client import get_notion_client
from ..content_converter import convert_to_notion_blocks

logger = logging.getLogger(__name__)
notion = get_notion_client()


def _split_text_into_chunks(text, max_length):
    """
    将文本分割成不超过最大长度的块

    参数：
    text (str): 要分割的文本
    max_length (int): 每个块的最大长度

    返回：
    list: 文本块列表
    """
    if not text:
        return []

    if len(text) <= max_length:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        # 确定当前块的结束位置
        end = start + max_length

        # 如果没有到达文本末尾，尝试找一个合适的断点
        if end < len(text):
            # 尝试在段落、句子或单词结束处断开
            # 优先级：段落 > 句子 > 单词 > 字符
            paragraph_end = text.rfind("\n\n", start, end)
            sentence_end = text.rfind(". ", start, end)
            space_end = text.rfind(" ", start, end)

            # 选择最合适的断点
            if paragraph_end > start + max_length // 2:  # 至少有一半内容
                end = paragraph_end + 2  # 包含段落结束符
            elif sentence_end > start + max_length // 3:  # 至少有 1/3 内容
                end = sentence_end + 2  # 包含句号和空格
            elif space_end > start + max_length // 4:  # 至少有 1/4 内容
                end = space_end + 1  # 包含空格
            else:
                # 如果找不到好的断点，就严格按照最大长度截断
                end = start + max_length

        # 添加当前块
        chunks.append(text[start:end])
        start = end

    return chunks


def process_blocks_content(blocks, max_length=2000):
    """
    处理块列表，确保每个块中的富文本内容不超过最大长度限制

    参数：
    blocks (list): Notion 块列表
    max_length (int): 富文本内容的最大长度

    返回：
    list: 处理后的块列表
    """
    processed_blocks = []

    for block in blocks:
        block_type = block.get("type")
        if not block_type:
            processed_blocks.append(block)
            continue

        # 处理代码块
        if block_type == "code" and "code" in block and "rich_text" in block["code"]:
            if block["code"]["rich_text"] and "text" in block["code"]["rich_text"][0]:
                content = block["code"]["rich_text"][0]["text"]["content"]

                if len(content) > max_length:
                    # 分割内容
                    chunks = _split_text_into_chunks(content, max_length)
                    language = block["code"]["language"]

                    # 创建多个代码块
                    for i, chunk in enumerate(chunks):
                        code_block = {
                            "object": "block",
                            "type": "code",
                            "code": {
                                "rich_text": [
                                    {"type": "text", "text": {"content": chunk}}
                                ],
                                "language": language,
                            },
                        }
                        # 如果是多块中的一个，添加注释
                        if len(chunks) > 1:
                            prefix = (
                                f"# 第 {i + 1}/{len(chunks)} 部分\n" if i > 0 else ""
                            )
                            code_block["code"]["rich_text"][0]["text"]["content"] = (
                                prefix + chunk
                            )

                        processed_blocks.append(code_block)
                else:
                    processed_blocks.append(block)
            else:
                # 如果没有文本内容，直接添加块
                processed_blocks.append(block)

        # 处理其他包含 rich_text 的块类型
        elif block_type in [
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "quote",
            "callout",
        ]:
            if block_type in block and "rich_text" in block[block_type]:
                if (
                    block[block_type]["rich_text"]
                    and "text" in block[block_type]["rich_text"][0]
                ):
                    content = block[block_type]["rich_text"][0]["text"]["content"]

                    if len(content) > max_length:
                        # 分割内容
                        chunks = _split_text_into_chunks(content, max_length)

                        # 添加第一个块（保持原块类型）
                        first_block = block.copy()  # 创建原块的副本
                        first_block[block_type]["rich_text"][0]["text"]["content"] = (
                            chunks[0]
                        )
                        processed_blocks.append(first_block)

                        # 其余内容作为段落添加
                        for chunk in chunks[1:]:
                            para_block = {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": [
                                        {"type": "text", "text": {"content": chunk}}
                                    ]
                                },
                            }
                            processed_blocks.append(para_block)
                    else:
                        processed_blocks.append(block)
                else:
                    # 处理没有文本内容的富文本块
                    processed_blocks.append(block)
            else:
                processed_blocks.append(block)
        # 处理可能嵌套的块
        elif block_type == "toggle" and "toggle" in block:
            # 处理 toggle 块的标题文本
            if (
                "rich_text" in block["toggle"]
                and block["toggle"]["rich_text"]
                and "text" in block["toggle"]["rich_text"][0]
            ):
                content = block["toggle"]["rich_text"][0]["text"]["content"]
                if len(content) > max_length:
                    chunks = _split_text_into_chunks(content, max_length)
                    block["toggle"]["rich_text"][0]["text"]["content"] = chunks[0]

                    # 额外的内容会在子块中处理

            # 递归处理子块
            if "children" in block["toggle"]:
                block["toggle"]["children"] = process_blocks_content(
                    block["toggle"]["children"], max_length
                )

            processed_blocks.append(block)
        # 处理表格行和单元格
        elif block_type == "table" and "table" in block:
            # 表格本身不包含文本内容，但需要处理其行
            if "children" in block:
                block["children"] = process_blocks_content(
                    block["children"], max_length
                )
            processed_blocks.append(block)
        elif block_type == "table_row" and "table_row" in block:
            # 处理表格行中的单元格
            for cell in block["table_row"]["cells"]:
                for rt in cell:
                    if "text" in rt and "content" in rt["text"]:
                        content = rt["text"]["content"]
                        if len(content) > max_length:
                            rt["text"]["content"] = content[:max_length]
            processed_blocks.append(block)
        # 处理列表块
        elif block_type in ["bulleted_list", "numbered_list"] and "children" in block:
            # 递归处理子块
            block["children"] = process_blocks_content(block["children"], max_length)
            processed_blocks.append(block)
        else:
            # 其他块类型直接添加
            processed_blocks.append(block)

    return processed_blocks


def add_to_notion(content, summary, tags, url="", created_at=None):
    """
    将内容添加到 Notion 数据库

    参数：
    content (str): 消息内容
    summary (str): AI 生成的摘要
    tags (list): 合并后的标签列表（包含原始hashtag标签和AI生成的标签）
    url (str): 可选的 URL
    created_at (datetime): 创建时间

    返回：
    dict: 包含 page_id, title, url 的字典
    """
    if not created_at:
        created_at = datetime.now()
        # 修复时区问题
        created_at = created_at.astimezone(pytz.timezone("Asia/Shanghai"))

    # 确定页面标题
    title = determine_title(content, url, summary)

    # 准备标签格式 - 确保标签不为空且去重
    tag_objects = []
    if tags:
        # 去重并过滤空标签
        unique_tags = []
        for tag in tags:
            if tag and tag.strip() and tag.strip() not in unique_tags:
                unique_tags.append(tag.strip())
        
        # 转换为 Notion 格式
        for tag in unique_tags:
            tag_objects.append({"name": tag})
        
        logger.info(f"准备添加 {len(tag_objects)} 个标签到 Notion: {[t['name'] for t in tag_objects]}")

    # 将内容转换为 Notion 块格式
    content_blocks = convert_to_notion_blocks(content)

    # 处理可能超过长度限制的块
    content_blocks = process_blocks_content(content_blocks)

    # 截断摘要，确保不超过 2000 个字符
    truncated_summary = summary[:2000] if summary else ""

    # 创建 Notion 页面
    try:
        # 块的数量
        blocks_count = len(content_blocks)

        # 如果块数量超过 API 限制 (100)，我们需要分批添加
        if blocks_count > 100:
            logger.info(f"内容包含 {blocks_count} 个块，超过 API 限制，将分批添加")

            # 先创建没有子块的页面
            new_page = notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Summary": {
                        "rich_text": [{"text": {"content": truncated_summary}}]
                    },
                    "Tags": {"multi_select": tag_objects},
                    "URL": {"url": url if url else None},
                    "Created": {"date": {"start": created_at.isoformat()}},
                },
            )

            # 获取新创建页面的 ID
            page_id = new_page["id"]

            # 然后分批添加子块
            append_blocks_in_batches(page_id, content_blocks)

            logger.info(
                f"成功创建 Notion 页面并分批添加 {blocks_count} 个块：{page_id}"
            )
            return {
                "page_id": page_id,
                "title": title,
                "url": f"https://notion.so/{page_id.replace('-', '')}"
            }
        else:
            # 如果块数量不超过限制，直接创建带有子块的页面
            new_page = notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Summary": {
                        "rich_text": [{"text": {"content": truncated_summary}}]
                    },
                    "Tags": {"multi_select": tag_objects},
                    "URL": {"url": url if url else None},
                    "Created": {"date": {"start": created_at.isoformat()}},
                },
                children=content_blocks,
            )

            logger.info(
                f"成功创建 Notion 页面：{new_page['id']}，包含 {len(content_blocks)} 个块"
            )
            page_id = new_page["id"]
            return {
                "page_id": page_id,
                "title": title,
                "url": f"https://notion.so/{page_id.replace('-', '')}"
            }

    except Exception as e:
        logger.error(f"创建 Notion 页面时出错：{e}")
        raise


def append_blocks_in_batches(page_id, blocks, batch_size=100):
    """
    分批将块添加到 Notion 页面

    参数：
    page_id (str): Notion 页面 ID
    blocks (list): 要添加的块列表
    batch_size (int): 每批最大块数，默认 100 (Notion API 限制)

    返回：
    bool: 是否成功添加所有块
    """
    # 确保所有块都不超过最大长度限制
    blocks = process_blocks_content(blocks)

    total_blocks = len(blocks)
    batches_count = (total_blocks + batch_size - 1) // batch_size  # 向上取整

    logger.info(f"开始分批添加 {total_blocks} 个块，分为 {batches_count} 批")

    for i in range(0, total_blocks, batch_size):
        batch = blocks[i : i + batch_size]
        batch_num = i // batch_size + 1

        try:
            # 添加一批块
            notion.blocks.children.append(block_id=page_id, children=batch)

            logger.info(
                f"成功添加第 {batch_num}/{batches_count} 批，包含 {len(batch)} 个块"
            )

            # 添加短暂延迟避免请求过于频繁
            if batch_num < batches_count:
                time.sleep(0.5)

        except Exception as e:
            logger.error(f"添加第 {batch_num}/{batches_count} 批块时出错：{e}")

            # 尝试细分批次重试
            if len(batch) > 10:
                logger.info("尝试将批次细分后重试...")
                smaller_batch_size = len(batch) // 2
                success = append_blocks_in_batches(page_id, batch, smaller_batch_size)
                if not success:
                    return False
            else:
                # 如果批次已经很小仍然失败，则跳过该批次
                logger.warning(f"跳过添加失败的 {len(batch)} 个块")

    return True


# TODO: 重构 determine_title
def determine_title(content, url, summary):
    """基于内容、URL  and 摘要确定标题"""
    # 如果内容很短，直接使用内容作为标题
    if len(content) <= 100:
        return content

    # 如果有 URL  and 摘要，使用摘要的第一句
    # if url  and summary:
    #     first_sentence = summary.split(".")[0]
    #     # 确保标题长度不超过 50 个字符
    #     if len(first_sentence) > 50:
    #         return first_sentence[:47] + "..."
    #     return first_sentence + "..."

    # 默认使用内容的前一部分作为标题
    return analyze_content(content)["title"]


def get_weekly_entries(days=7):
    """
    获取过去几天内添加的所有条目

    参数：
    days (int): 要检索的天数

    返回：
    list: Notion 页面对象列表
    """
    from datetime import datetime, timedelta

    # 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    # 查询 Notion 数据库
    try:
        response = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "and": [
                    {
                        "property": "Created",
                        "date": {"on_or_after": start_date.isoformat()},
                    }
                ]
            },
            sorts=[{"property": "Created", "direction": "ascending"}],
        )

        return response["results"]

    except Exception as e:
        logger.error(f"查询 Notion 数据库时出错：{e}")
        raise


def create_weekly_report(title, content):
    """
    创建周报页面

    参数：
    title (str): 周报标题
    content (str): 周报内容，可以包含 [引用文本](ref:页面 ID) 格式的引用

    返回：
    str: 创建的页面 URL
    """
    try:
        # 将内容中的引用格式 [标题](ref:页面 ID) 转换为 Notion 内链格式
        logger.info("处理周报中的页面引用...")
        processed_content = process_notion_references(content)

        # 将内容转换为 Notion block 格式，支持内链
        blocks = convert_to_notion_blocks(processed_content)

        # 处理可能超过长度限制的块
        blocks = process_blocks_content(blocks)

        # 创建页面
        blocks_count = len(blocks)

        # 如果块数量超过 API 限制，分批添加
        if blocks_count > 100:
            logger.info(f"周报包含 {blocks_count} 个块，超过 API 限制，将分批添加")

            # 先创建没有子块的页面
            new_page = notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Tags": {"multi_select": [{"name": "周报"}]},
                    "Created": {"date": {"start": datetime.now().isoformat()}},
                },
            )

            # 获取新创建页面的 ID
            page_id = new_page["id"]

            # 然后分批添加子块
            append_blocks_in_batches(page_id, blocks)

            logger.info(f"成功创建周报页面并分批添加 {blocks_count} 个块：{page_id}")
        else:
            new_page = notion.pages.create(
                parent={"database_id": NOTION_DATABASE_ID},
                properties={
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Tags": {"multi_select": [{"name": "周报"}]},
                    "Created": {"date": {"start": datetime.now().isoformat()}},
                },
                children=blocks,
            )

            page_id = new_page["id"]
            logger.info(f"成功创建周报页面：{page_id}，包含 {len(blocks)} 个块")

        # 返回页面 URL
        return f"https://notion.so/{page_id.replace('-', '')}"

    except Exception as e:
        logger.error(f"创建周报页面时出错：{e}")
        raise


def process_notion_references(content):
    """
    处理文本中的 Notion 引用标记，转换为 Notion 链接格式
    支持格式：[引用文本](ref:页面 ID)

    参数：
    content (str): 包含 [引用文本](ref:页面 ID) 格式引用的文本

    返回：
    str: 转换后的文本，引用转为 Notion 可识别的内链格式
    """
    import re

    # 查找格式为 [引用文本](ref:页面 ID) 的引用
    pattern = r"\[(.*?)\]\(ref:([a-zA-Z0-9-]+)\)"

    def replace_ref(match):
        text = match.group(1)
        page_id = match.group(2)

        # 返回 Notion 页面链接格式 - 这会被 convert_to_notion_blocks 函数进一步处理
        # 确保 ID 格式正确（移除连字符，因为 Notion URL 中不使用）
        clean_id = page_id.replace("-", "")
        return f"[{text}](https://notion.so/{clean_id})"

    # 替换所有匹配项
    processed_text = re.sub(pattern, replace_ref, content)

    # 记录处理情况
    original_refs_count = len(re.findall(pattern, content))
    processed_refs_count = len(
        re.findall(r"\[(.*?)\]\(https://notion\.so/[a-zA-Z0-9]+\)", processed_text)
    )

    logger.info(
        f"处理了 {original_refs_count} 个引用，转换了 {processed_refs_count} 个 Notion 内链"
    )

    return processed_text


def generate_weekly_content(entries):
    """
    根据本周条目生成周报内容，并自动创建内链引用

    参数：
    entries (list): 本周 Notion 页面对象列表

    返回：
    str: 格式化的周报内容，包含内链引用
    """
    content = []
    content.append("# 本周内容总结\n")

    # 按日期分组
    entries_by_date = {}
    for entry in entries:
        # 跳过周报本身
        if "Tags" in entry["properties"] and any(
            tag.get("name") == "周报"
            for tag in entry["properties"]["Tags"].get("multi_select", [])
        ):
            continue

        # 获取条目创建日期
        created_date = None
        if "Created" in entry["properties"] and entry["properties"]["Created"].get(
            "date"
        ):
            date_str = entry["properties"]["Created"]["date"].get("start")
            if date_str:
                created_date = date_str.split("T")[0]  # 仅保留日期部分 YYYY-MM-DD

        if not created_date:
            created_date = "未知日期"

        if created_date not in entries_by_date:
            entries_by_date[created_date] = []

        entries_by_date[created_date].append(entry)

    # 按日期排序
    for date in sorted(entries_by_date.keys()):
        content.append(f"## {date}\n")

        # 添加每个条目的摘要 and 内链
        for entry in entries_by_date[date]:
            # 获取条目标题
            title = "无标题"
            if "Name" in entry["properties"] and entry["properties"]["Name"].get(
                "title"
            ):
                title_objects = entry["properties"]["Name"]["title"]
                if title_objects and "plain_text" in title_objects[0]:
                    title = title_objects[0]["plain_text"]
                elif (
                    title_objects
                    and "text" in title_objects[0]
                    and "content" in title_objects[0]["text"]
                ):
                    title = title_objects[0]["text"]["content"]

            # 获取条目摘要
            summary = ""
            if "Summary" in entry["properties"] and entry["properties"]["Summary"].get(
                "rich_text"
            ):
                summary_objects = entry["properties"]["Summary"]["rich_text"]
                if summary_objects and "plain_text" in summary_objects[0]:
                    summary = summary_objects[0]["plain_text"]
                elif (
                    summary_objects
                    and "text" in summary_objects[0]
                    and "content" in summary_objects[0]["text"]
                ):
                    summary = summary_objects[0]["text"]["content"]

            # 尝试获取内容块以提取更多详细信息
            try:
                page_content = notion.blocks.children.list(block_id=entry["id"])
                content_text = extract_notion_block_content(
                    page_content.get("results", [])
                )

                # 如果提取到内容，使用内容的前一部分作为摘要展示
                if content_text and not summary:
                    summary = truncate_text(content_text, 150)  # 限制摘要长度
            except Exception as e:
                logger.warning(f"提取页面内容时出错：{e}")

            # 截断摘要
            if len(summary) > 150:
                summary = summary[:147] + "..."

            # 生成包含内链的摘要行
            page_id = entry["id"]

            # 使用 ref: 格式，方便后续使用 process_notion_references 处理
            content.append(f"- [{title}](ref:{page_id}): {summary}")

        content.append("")  # 添加空行分隔不同日期的内容

    # 添加结尾，等待 AI 生成的总结
    content.append("# AI 周报总结\n")
    content.append("_以下内容由 AI 自动生成_\n")

    return "\n".join(content)


def extract_notion_block_content(blocks):
    """
    从 Notion 块中提取文本内容，确保内容不超过 API 限制

    参数：
    blocks (list): Notion 块列表

    返回：
    str: 提取的文本内容
    """
    content = []
    MAX_TEXT_LENGTH = 2000  # Notion API 文本长度限制

    for block in blocks:
        block_type = block.get("type")
        if not block_type:
            continue

        block_data = block.get(block_type)
        if not block_data:
            continue

        # 处理不同类型的块
        if block_type == "paragraph":
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                content.append(text)
        elif block_type in ["heading_1", "heading_2", "heading_3"]:
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                # 添加标题标记
                prefix = "#" * int(block_type[-1])
                content.append(f"{prefix} {text}")
        elif block_type == "bulleted_list_item":
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                content.append(f"- {text}")
        elif block_type == "numbered_list_item":
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                content.append(f"1. {text}")  # 简化处理，所有项目都用 1.
        elif block_type == "quote":
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                content.append(f"> {text}")
        elif block_type == "callout":
            text = extract_rich_text(block_data.get("rich_text", []))
            if text:
                icon = ""
                if "icon" in block_data and "emoji" in block_data["icon"]:
                    icon = block_data["icon"]["emoji"] + " "
                content.append(f"> {icon}{text}")
        elif block_type == "code":
            text = extract_rich_text(block_data.get("rich_text", []))
            language = block_data.get("language", "")

            # 处理代码块，确保不超过最大长度
            if text:
                # 如果代码内容超过最大长度，分割成多个代码块
                if len(text) > MAX_TEXT_LENGTH:
                    # 按最大长度分块，每个块不超过最大长度
                    for i in range(0, len(text), MAX_TEXT_LENGTH):
                        chunk = text[i : i + MAX_TEXT_LENGTH]
                        if i == 0:  # 第一个块
                            content.append(f"```{language}\n{chunk}")
                        elif i + MAX_TEXT_LENGTH >= len(text):  # 最后一个块
                            content.append(f"{chunk}\n```")
                        else:  # 中间块
                            content.append(chunk)
                else:
                    content.append(f"```{language}\n{text}\n```")

    return "\n".join(content)


def extract_rich_text(rich_text):
    """
    从富文本数组中提取纯文本

    参数：
    rich_text (list): Notion 富文本对象列表

    返回：
    str: 提取的纯文本
    """
    if not rich_text:
        return ""

    return "".join([rt.get("plain_text", "") for rt in rich_text])


def create_auto_weekly_report():
    """
    自动创建包含本周所有条目的周报

    返回：
    str: 创建的周报页面 URL
    """
    # 获取本周日期范围
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    week_number = today.isocalendar()[1]

    # 创建周报标题
    title = f"周报 {today.year} 第{week_number}周 ({start_of_week.strftime('%m.%d')}-{end_of_week.strftime('%m.%d')})"

    # 获取本周条目
    entries = get_weekly_entries(days=7)

    # 生成周报内容
    content = generate_weekly_content(entries)

    # 将内容转换为 Notion block 格式，支持内链
    blocks = convert_to_notion_blocks(content)

    # 处理可能超过长度限制的块
    blocks = process_blocks_content(blocks)

    # 创建周报
    report_url = create_weekly_report(title, content)

    logger.info(f"成功创建周报：{title} ({report_url})")
    return report_url
