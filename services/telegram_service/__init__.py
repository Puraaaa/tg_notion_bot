# 导出所有需要的函数和类，保持原有 API 不变
from .client import error_handler, setup_telegram_bot
from .handlers.command_handlers import help_command, start, weekly_report_command
from .handlers.message_handlers import process_document, process_message
from .handlers.pdf_handlers import handle_pdf_document, handle_pdf_url
from .handlers.todo_handlers import handle_todo_message
from .handlers.url_handlers import handle_multiple_urls_message, handle_url_message
from .message_queue import MessageOffsetManager, MessageQueueProcessor, ReconnectionManager
from .utils import (
    enrich_analysis_with_metadata,
    extract_metadata_from_filename,
    prepare_metadata_for_notion,
)

# 确保函数被正确导出
__all__ = [
    "setup_telegram_bot",
    "start",
    "help_command",
    "process_message",
    "handle_url_message",
    "handle_todo_message",
    "process_document",
    "handle_pdf_document",
    "weekly_report_command",
    "handle_pdf_url",
    "handle_multiple_urls_message",
    "enrich_analysis_with_metadata",
    "error_handler",
    "extract_metadata_from_filename",
    "prepare_metadata_for_notion",
    "MessageOffsetManager",
    "MessageQueueProcessor",
    "ReconnectionManager",
]
