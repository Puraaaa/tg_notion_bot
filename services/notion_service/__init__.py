# 导出所有需要的函数和类，保持原有 API 不变
from .client import get_notion_client, notion
from .content_converter import (
    convert_to_notion_blocks,
    create_text_blocks_from_content,
    limit_blocks,
    parse_markdown_formatting,
    split_text,
)
from .database.common import (
    add_to_notion,
    append_blocks_in_batches,
    create_auto_weekly_report,
    create_weekly_report,
    determine_title,
    extract_notion_block_content,
    extract_rich_text,
    generate_weekly_content,
    get_weekly_entries,  # 添加这个函数导入
    process_notion_references,
)
from .database.papers import (
    add_to_papers_database,
    check_paper_exists_in_notion,
    download_pdf,
    get_existing_dois,
    get_existing_zotero_ids,
    is_pdf_url,
    prepare_metadata_for_notion,
)
from .database.todo import add_to_todo_database
from .file_upload import (
    create_file_property_value,
    create_image_block,
    upload_image_to_notion,
    upload_multiple_images,
)

__all__ = [
    "get_notion_client",
    "notion",
    "prepare_metadata_for_notion",
    "check_paper_exists_in_notion",
    "is_pdf_url",
    "download_pdf",
    "add_to_notion",
    "add_to_todo_database",
    "add_to_papers_database",
    "get_existing_dois",
    "get_existing_zotero_ids",
    "extract_notion_block_content",
    "extract_rich_text",
    "process_notion_references",
    "generate_weekly_content",
    "convert_to_notion_blocks",
    "parse_markdown_formatting",
    "split_text",
    "create_text_blocks_from_content",
    "limit_blocks",
    "create_weekly_report",
    "create_auto_weekly_report",
    "append_blocks_in_batches",
    "determine_title",
    "get_weekly_entries",  # 添加到 __all__ 列表
    "upload_image_to_notion",
    "upload_multiple_images",
    "create_file_property_value",
    "create_image_block",
]
