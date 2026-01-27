# 消息队列处理机制

## 概述

本功能实现了 Telegram Bot 断联重连后的消息队列处理机制，确保在网络中断、服务重启或其他异常情况下，Bot 能够可靠地处理所有消息，不会丢失或重复处理。

## 核心功能

### 1. 消息偏移量管理 (MessageOffsetManager)

- **持久化存储**: 使用 SQLite 数据库存储最后处理的 `update_id`
- **防重复处理**: 跟踪已处理的消息，避免重复处理
- **自动清理**: 定期清理旧的处理记录，保持数据库精简

```python
# 初始化偏移量管理器
offset_manager = MessageOffsetManager("data/message_offset.db")

# 获取最后处理的偏移量
last_offset = offset_manager.get_last_offset()

# 更新偏移量
offset_manager.update_offset(new_update_id)

# 检查消息是否已处理
is_processed = offset_manager.is_message_processed(update_id)
```

### 2. 消息队列处理器 (MessageQueueProcessor)

- **批量处理**: 支持批量获取和处理积压消息
- **API 限流保护**: 内置处理延迟，避免触发 Telegram API 限流
- **错误恢复**: 处理失败的消息会被记录，不影响其他消息处理

```python
# 初始化队列处理器
processor = MessageQueueProcessor(bot, offset_manager)

# 处理积压消息
message_handlers = {'message': your_message_handler}
processed, failed = processor.process_backlog_messages(message_handlers)
```

### 3. 重连管理器 (ReconnectionManager)

- **连接监控**: 定期检查与 Telegram API 的连接状态
- **自动恢复**: 检测到重连后自动处理积压消息
- **状态跟踪**: 维护连接和恢复状态

```python
# 初始化重连管理器
reconnection_manager = ReconnectionManager(bot, queue_processor)

# 检查连接并恢复消息
is_connected = reconnection_manager.check_connection_and_recover(message_handlers)
```

## 集成方式

### 在 main.py 中的集成

```python
# 初始化消息队列组件
_offset_manager = MessageOffsetManager()
_queue_processor = MessageQueueProcessor(updater.bot, _offset_manager)
_reconnection_manager = ReconnectionManager(updater.bot, _queue_processor)

# 启动时处理积压消息
message_handlers = _get_message_handlers()
processed, failed = _queue_processor.process_backlog_messages(message_handlers)

# 在连接检查线程中使用重连管理器
_reconnection_manager.check_connection_and_recover(message_handlers)
```

### 配置选项

- **批处理大小**: 默认每批处理 100 条消息
- **处理延迟**: 默认每条消息间隔 0.1 秒
- **连接检查间隔**: 默认 5 分钟检查一次连接
- **记录保留期**: 默认保留 7 天的处理记录

## 数据库结构

### message_offset 表
```sql
CREATE TABLE message_offset (
    id INTEGER PRIMARY KEY,
    last_update_id INTEGER NOT NULL,
    last_processed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### processed_messages 表
```sql
CREATE TABLE processed_messages (
    update_id INTEGER PRIMARY KEY,
    message_id INTEGER,
    chat_id INTEGER,
    processed_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    message_type TEXT
);
```

## 工作流程

1. **正常运行**: Bot 正常处理消息，实时更新偏移量
2. **断联检测**: 连接检查线程检测到网络异常
3. **状态标记**: 重连管理器标记为恢复状态
4. **重连成功**: 检测到连接恢复
5. **消息恢复**: 从上次偏移量开始获取积压消息
6. **批量处理**: 分批处理积压消息，避免 API 限流
7. **状态更新**: 处理完成后更新偏移量和处理状态

## 验收标准

✅ **Bot 重启后能自动获取断联期间的所有消息**
- 通过偏移量管理器实现，从上次处理位置继续

✅ **消息按发送时间顺序正确处理**
- 使用 Telegram API 的 `update_id` 保证顺序

✅ **不会重复处理已处理过的消息**
- 通过 `processed_messages` 表跟踪处理状态

✅ **支持处理大量积压消息（100+ 条）**
- 批量处理机制，测试验证可处理 150+ 条消息

✅ **处理过程中的错误能被正确记录和处理**
- 完整的异常处理和日志记录

✅ **添加相关的单元测试**
- 15 个测试用例，覆盖所有核心功能

## 测试

运行完整测试套件：
```bash
python -m pytest tests/test_message_queue.py -v
```

运行演示脚本：
```bash
python demo_message_queue.py
```

## 性能考虑

- **内存使用**: 批量处理避免一次性加载大量消息
- **API 限流**: 内置延迟机制防止触发 Telegram API 限制
- **数据库优化**: 定期清理旧记录，保持查询性能
- **并发安全**: 使用 SQLite 的事务机制保证数据一致性

## 故障排除

### 常见问题

1. **数据库锁定**: 确保没有多个进程同时访问数据库
2. **权限问题**: 确保 `data/` 目录有写入权限
3. **网络超时**: 调整连接超时参数
4. **内存不足**: 减少批处理大小

### 日志级别

- `INFO`: 正常操作日志
- `WARNING`: 连接问题和重试
- `ERROR`: 严重错误和异常
- `DEBUG`: 详细的处理过程

## 未来改进

- [ ] 支持消息优先级处理
- [ ] 添加消息处理统计和监控
- [ ] 支持分布式部署的消息同步
- [ ] 添加消息处理性能指标
- [ ] 支持自定义重试策略