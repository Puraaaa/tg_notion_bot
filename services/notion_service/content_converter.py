import logging
import re

logger = logging.getLogger(__name__)


def convert_to_notion_blocks(content):
    """
    将文本内容转换为 Notion 块格式，支持 Markdown 语法

    参数：
    content (str): 要转换的文本内容

    返回：
    list: Notion 块对象列表
    """

    # Notion API 文本块长度限制
    MAX_TEXT_LENGTH = 2000

    # 如果内容为空，返回简单段落
    if not content or len(content.strip()) == 0:
        return [
            {"object": "block", "paragraph": {"rich_text": [{"text": {"content": ""}}]}}
        ]

    # 将内容分成行
    lines = content.split("\n")
    blocks = []

    i = 0
    current_list_type = None  # 'bulleted'  or 'numbered'
    list_levels = []  # 保存当前层级的列表项信息

    while i < len(lines):
        line = lines[i].strip()

        # 处理标题 (# 标题)
        header_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if header_match:
            # 如果之前在处理列表，结束列表
            current_list_type = None
            list_levels = []

            level = len(header_match.group(1))
            heading_text = header_match.group(2)

            # 确保标题文本不超过限制
            if len(heading_text) > MAX_TEXT_LENGTH:
                heading_text = heading_text[: MAX_TEXT_LENGTH - 3] + "..."

            heading_type = f"heading_{level}"
            blocks.append(
                {
                    "object": "block",
                    heading_type: {
                        "rich_text": parse_markdown_formatting(heading_text)
                    },
                }
            )
            i += 1
            continue

        # 处理列表项，支持多级列表
        # 检查列表项的缩进级别
        list_match = re.match(r"^(\s*)[-*]\s+(.+)$", line)
        if list_match:
            indent = len(list_match.group(1))
            list_text = list_match.group(2)

            # 确定列表级别 (基于缩进)
            indent_level = indent // 2  # 假设每级缩进为 2 个空格

            # 更新列表级别信息
            if current_list_type != "bulleted" or indent_level != len(list_levels):
                # 新的列表类型 or 新的缩进级别
                current_list_type = "bulleted"

                # 调整 list_levels 以匹配当前级别
                if indent_level > len(list_levels):
                    # 增加缩进级别
                    while len(list_levels) < indent_level:
                        list_levels.append("bulleted")
                else:
                    # 减少缩进级别
                    list_levels = list_levels[:indent_level]
                list_levels.append("bulleted")

            # 分割长列表项
            for chunk in split_text(list_text, MAX_TEXT_LENGTH):
                # 根据缩进级别创建嵌套结构
                block = {
                    "object": "block",
                    "bulleted_list_item": {
                        "rich_text": parse_markdown_formatting(chunk)
                    },
                }

                # 处理子项
                if indent_level > 0:
                    # 添加缩进信息
                    block["bulleted_list_item"]["color"] = "default"

                blocks.append(block)
            i += 1
            continue

        # 处理数字列表项，支持多级列表
        num_list_match = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if num_list_match:
            indent = len(num_list_match.group(1))
            num = num_list_match.group(2)  # noqa: F841
            list_text = num_list_match.group(3)

            # 确定列表级别 (基于缩进)
            indent_level = indent // 2  # 假设每级缩进为 2 个空格

            # 更新列表级别信息
            if current_list_type != "numbered" or indent_level != len(list_levels):
                current_list_type = "numbered"

                # 调整 list_levels 以匹配当前级别
                if indent_level > len(list_levels):
                    # 增加缩进级别
                    while len(list_levels) < indent_level:
                        list_levels.append("numbered")
                else:
                    # 减少缩进级别
                    list_levels = list_levels[:indent_level]
                list_levels.append("numbered")

            # 分割长列表项
            for chunk in split_text(list_text, MAX_TEXT_LENGTH):
                # 创建编号列表项
                block = {
                    "object": "block",
                    "numbered_list_item": {
                        "rich_text": parse_markdown_formatting(chunk)
                    },
                }

                # 处理子项
                if indent_level > 0:
                    # 添加缩进信息
                    block["numbered_list_item"]["color"] = "default"

                blocks.append(block)
            i += 1
            continue

        # 如果遇到空行 or 其他非列表项，重置列表状态
        if not line:
            current_list_type = None
            list_levels = []

        # 处理引用块 (> 引用)
        quote_match = re.match(r"^>\s+(.+)$", line)
        if quote_match:
            # 结束之前的列表
            current_list_type = None
            list_levels = []

            quote_text = quote_match.group(1)

            # 分割长引用
            for chunk in split_text(quote_text, MAX_TEXT_LENGTH):
                blocks.append(
                    {
                        "object": "block",
                        "quote": {"rich_text": parse_markdown_formatting(chunk)},
                    }
                )
            i += 1
            continue

        # 处理代码块 (```language 代码 ```)
        if line.startswith("```"):
            # 结束之前的列表
            current_list_type = None
            list_levels = []

            code_lang = line[3:].strip()
            code_content = []
            i += 1

            while i < len(lines) and not lines[i].strip().endswith("```"):
                code_content.append(lines[i])
                i += 1

            if i < len(lines):  # 找到了结束标记
                code_text = "\n".join(code_content)
                blocks.append(
                    {
                        "object": "block",
                        "code": {
                            "language": code_lang if code_lang else "plain text",
                            "rich_text": [{"text": {"content": code_text}}],
                        },
                    }
                )
                i += 1
                continue

        # 处理表格行 (| 列 1 | 列 2 | 列 3 |)
        table_match = re.match(r"^\s*\|(.+)\|\s*$", line)
        if table_match:
            # 检测到表格，但 Notion API 当前有一些限制，我们先跳过它
            # 在未来的版本可以处理表格转换
            current_list_type = None
            list_levels = []

            # 提取表格行的内容
            cells = [cell.strip() for cell in table_match.group(1).split("|")]

            # 把表格行转为普通文本
            table_line = "| " + " | ".join(cells) + " |"
            blocks.append(
                {
                    "object": "block",
                    "paragraph": {"rich_text": [{"text": {"content": table_line}}]},
                }
            )
            i += 1
            continue

        # 处理普通段落
        if line:
            # 结束之前的列表
            current_list_type = None
            list_levels = []

            # 分割长段落
            for chunk in split_text(line, MAX_TEXT_LENGTH):
                blocks.append(
                    {
                        "object": "block",
                        "paragraph": {"rich_text": parse_markdown_formatting(chunk)},
                    }
                )
        else:
            # 空行，添加空段落
            blocks.append({"object": "block", "paragraph": {"rich_text": []}})

        i += 1

    return blocks


def parse_markdown_formatting(text):
    """
    解析文本中的 Markdown 格式并转换为 Notion rich_text 格式

    支持：
    - **加粗**
    - *斜体*
    - ~~删除线~~
    - `代码`
    - [链接](URL)
    - [内容](https://notion.so/PAGE_ID) 作为 Notion 页面链接
    - (URL) - 括号包裹的 URL

    参数：
    text (str): 包含 Markdown 格式的文本

    返回：
    list: Notion rich_text 对象列表
    """

    # 如果文本为空，返回空列表
    if not text:
        return []

    # 创建一个结果列表
    result = []

    # 使用一个更精确的方法来处理格式化文本
    # 1. 首先识别所有特殊格式的位置 and 类型
    formats = []

    # 定义正则表达式模式
    patterns = [
        # Notion 页面链接 [text](https://notion.so/pageid)
        (r"\[(.+?)\]\(https://notion\.so/([a-zA-Z0-9]+)\)", "notion_page"),
        # 普通链接 [text](url)
        (r"\[(.+?)\]\((?!https://notion\.so/)(.+?)\)", "link"),
        # 括号包裹的 URL (http://example.com)
        (r"\((https?://[^\s\)]+)\)", "bracket_link"),
        # 加粗 **text**
        (r"\*\*(.+?)\*\*", "bold"),
        # 斜体 *text*
        (r"\*(.+?)\*", "italic"),
        # 删除线 ~~text~~
        (r"~~(.+?)~~", "strikethrough"),
        # 代码 `text`
        (r"`(.+?)`", "code"),
    ]

    # 查找所有格式标记的位置
    for pattern, format_type in patterns:
        for match in re.finditer(pattern, text):
            start, end = match.span()

            # 处理不同类型的格式
            if format_type == "notion_page":
                content = match.group(1)  # 链接文本
                page_id = match.group(2)  # 页面 ID
                formats.append((start, end, format_type, content, page_id))
            elif format_type == "link":
                content = match.group(1)  # 链接文本
                url = match.group(2)  # URL
                formats.append((start, end, format_type, content, url))
            elif format_type == "bracket_link":
                url = match.group(1)  # URL (不含括号)
                # 对于括号包裹的链接，使用 URL 本身作为显示文本
                formats.append((start, end, "link", url, url))
            else:
                content = match.group(1)  # 格式内的实际文本
                formats.append((start, end, format_type, content, None))

    # 2. 按照起始位置排序格式标记
    formats.sort(key=lambda x: x[0])

    # 3. 处理文本，避免重复
    if not formats:
        # 没有格式，直接返回纯文本
        return [{"text": {"content": text}}]

    # 处理有格式的文本
    last_end = 0
    processed = []  # 用来跟踪已处理的文本范围

    for start, end, format_type, content, link_data in formats:
        # 检查这个区域是否已被处理
        if any(s <= start < e or s < end <= e for s, e in processed):
            continue

        # 添加格式标记前的普通文本
        if start > last_end:
            plain_text = text[last_end:start]
            if plain_text:
                result.append({"text": {"content": plain_text}})

        # 添加格式化文本
        if format_type == "notion_page":
            # 创建页面引用/提及
            result.append(
                {
                    "mention": {"type": "page", "page": {"id": link_data}},
                    "plain_text": content,
                    "href": f"https://notion.so/{link_data}",
                }
            )
        else:
            # 标准文本格式
            rich_text = {"text": {"content": content}}

            if format_type == "link" and link_data:
                # 验证 URL 是否有效（必须是完整的 http/https URL）
                if link_data.startswith(("http://", "https://")):
                    rich_text["text"]["link"] = {"url": link_data}
                # 如果是相对路径或无效 URL，不添加链接，只保留文本

            # 设置文本的格式注释
            annotations = {
                "bold": False,
                "italic": False,
                "strikethrough": False,
                "code": False,
            }
            if format_type in annotations:
                annotations[format_type] = True
            rich_text["annotations"] = annotations

            result.append(rich_text)

        # 更新已处理的范围
        processed.append((start, end))
        last_end = end

    # 添加最后一段普通文本
    if last_end < len(text):
        result.append({"text": {"content": text[last_end:]}})

    return result


def split_text(text, max_length):
    """
    将文本分割成不超过最大长度的块

    参数：
    text (str): 要分割的文本
    max_length (int): 每块的最大长度

    返回：
    list: 文本块列表
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    for i in range(0, len(text), max_length):
        # 如果不是第一块，尽量在句子 or 单词边界分割
        if i > 0 and i + max_length < len(text):
            # 尝试在句子结束处分割（句号、问号、感叹号后面）
            end = min(i + max_length, len(text))
            break_point = max(
                text.rfind(". ", i, end),
                text.rfind("? ", i, end),
                text.rfind("! ", i, end),
            )

            # 如果没有找到句子结束，尝试在空格处分割
            if break_point < i:
                break_point = text.rfind(" ", i, end)

            # 如果仍然没有找到合适的分割点，则强制在最大长度处分割
            if break_point < i:
                break_point = i + max_length - 1
            else:
                # 包含分隔符
                break_point += 1

            chunks.append(text[i:break_point])
            i = break_point - 1  # 减 1 是因为循环会加回来
        else:
            chunks.append(text[i : i + max_length])

    return chunks


def create_text_blocks_from_content(
    content, block_type="paragraph", emoji=None, color=None
):
    """
    将长文本内容转换为多个 Notion 块，确保每个块不超过 2000 字符

    参数：
    content (str): 要转换的文本内容
    block_type (str): 块类型，如 'paragraph', 'callout', 'quote' 等
    emoji (str, optional): 如果是 callout 类型，可以指定 emoji 图标
    color (str, optional): 块的颜色，如 'default', 'blue', 'red' 等

    返回：
    list: Notion 块对象列表
    """
    if not content:
        return []

    # 根据块类型构建适当的 Markdown 格式
    if block_type == "paragraph":
        markdown_content = content
    elif block_type == "quote":
        # 将每行前面添加 > 符号以创建引用块
        markdown_content = "\n".join([f"> {line}" for line in content.split("\n")])
    elif block_type == "callout":
        # 由于 convert_to_notion_blocks 不直接支持 callout，我们仍然使用原始方法
        blocks = []
        text_parts = split_text(content, 2000)

        for i, part in enumerate(text_parts):
            block = {
                "object": "block",
                "callout": {"rich_text": [{"text": {"content": part}}]},
            }

            if emoji and i == 0:
                block["callout"]["icon"] = {"emoji": emoji}

            if color:
                block["callout"]["color"] = color

            blocks.append(block)
        return blocks
    else:
        # 默认处理为普通段落
        markdown_content = content

    # 使用 convert_to_notion_blocks 处理 Markdown 格式的内容
    blocks = convert_to_notion_blocks(markdown_content)

    # 如果需要添加颜色属性
    if color and blocks:
        for block in blocks:
            # 确定正确的块类型键
            block_key = None
            for key in block:
                if key != "object" and isinstance(block[key], dict):
                    block_key = key
                    break

            if block_key:
                block[block_key]["color"] = color

    return blocks


def limit_blocks(blocks, max_blocks=100):
    """
    限制 Notion 块的数量 and 内容长度，确保不超过 API 限制

    参数：
    blocks (list): Notion 块列表
    max_blocks (int): 最大块数量，默认为 100（Notion API 限制）

    返回：
    list: 限制后的块列表
    """
    if not blocks:
        return []

    MAX_TEXT_LENGTH = 2000  # Notion API 文本长度限制
    processed_blocks = []
    blocks_processed = 0

    # 注意：我们不再截断内容，而是处理每个块以确保它能被 API 接受
    # 移除之前的 actual_max_blocks 限制，以处理所有块

    # 处理所有块，确保每个块的内容不超过限制
    for block in blocks:
        blocks_processed += 1
        block_type = block.get("object", "block")

        # 处理不同类型的块
        if block_type == "block":
            # 获取块类型（paragraph, heading_x, code 等）
            content_type = list(block.keys())[0] if block else None
            if not content_type or content_type == "object":
                content_type = list(block.keys())[1] if len(block.keys()) > 1 else None

            if content_type:
                # 处理代码块（特别需要注意，因为它们通常包含较长文本）
                if content_type == "code" and "rich_text" in block["code"]:
                    code_content = ""
                    if (
                        block["code"]["rich_text"]
                        and "text" in block["code"]["rich_text"][0]
                    ):
                        code_content = block["code"]["rich_text"][0]["text"].get(
                            "content", ""
                        )

                    # 如果代码内容超出限制，分割成多个代码块
                    if len(code_content) > MAX_TEXT_LENGTH:
                        language = block["code"].get("language", "plain text")
                        # 分割代码内容
                        code_chunks = []
                        for i in range(0, len(code_content), MAX_TEXT_LENGTH):
                            chunk = code_content[i : i + MAX_TEXT_LENGTH]
                            code_chunks.append(
                                {
                                    "object": "block",
                                    "code": {
                                        "language": language,
                                        "rich_text": [{"text": {"content": chunk}}],
                                    },
                                }
                            )

                        processed_blocks.extend(code_chunks)
                    else:
                        processed_blocks.append(block)

                # 处理段落、标题 and 其他文本块
                elif content_type in [
                    "paragraph",
                    "heading_1",
                    "heading_2",
                    "heading_3",
                    "bulleted_list_item",
                    "numbered_list_item",
                    "quote",
                    "callout",
                ]:
                    rich_text_key = content_type
                    if rich_text_key in block and "rich_text" in block[rich_text_key]:
                        rich_texts = block[rich_text_key]["rich_text"]

                        # 计算总文本长度
                        total_length = sum(
                            len(rt.get("text", {}).get("content", ""))
                            for rt in rich_texts
                            if "text" in rt
                        )

                        if total_length > MAX_TEXT_LENGTH:
                            # 如果总长度超出限制，创建新的简化文本块
                            combined_text = "".join(
                                rt.get("text", {}).get("content", "")
                                for rt in rich_texts
                                if "text" in rt
                            )
                            text_chunks = []

                            # 分割文本并创建多个块
                            for i in range(0, len(combined_text), MAX_TEXT_LENGTH):
                                chunk = combined_text[i : i + MAX_TEXT_LENGTH]
                                new_block = {
                                    "object": "block",
                                    content_type: {
                                        "rich_text": [{"text": {"content": chunk}}]
                                    },
                                }

                                # 保留原始块的其他属性（如颜色）
                                for key, value in block[content_type].items():
                                    if key != "rich_text":
                                        new_block[content_type][key] = value

                                text_chunks.append(new_block)

                            processed_blocks.extend(text_chunks)
                        else:
                            processed_blocks.append(block)
                else:
                    # 其他类型的块直接添加
                    processed_blocks.append(block)
            else:
                processed_blocks.append(block)
        else:
            processed_blocks.append(block)

    # 记录处理结果
    logger.info(
        f"处理了 {blocks_processed} 个块，生成了 {len(processed_blocks)} 个处理后的块"
    )

    return processed_blocks
