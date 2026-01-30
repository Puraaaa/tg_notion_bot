# TG Notion Bot 项目开发指南

## Linear 项目管理

### 团队信息
- **Team**: Development Team (DEV)
- **Issue 前缀**: DEV-xxx

### 创建 Issue
```
使用 mcp__plugin_linear_linear__create_issue 工具：
- team: "Development Team"
- title: Issue 标题
- description: Markdown 格式描述
- priority: 1=Urgent, 2=High, 3=Normal, 4=Low
- labels: ["Bug"] 或 ["Feature"] 等
```

### 更新 Issue 状态
```
使用 mcp__plugin_linear_linear__update_issue 工具：
- id: Issue UUID
- state: "In Progress" | "Done" | "Todo" | "Canceled"
```

### 查询 Issue
```
使用 mcp__plugin_linear_linear__list_issues 工具：
- query: "DEV-xxx" 或关键词
- assignee: "me" 查看我的任务
```

## 环境配置

### Conda 虚拟环境
- **环境名称**: tg-notion-bot
- **Python 版本**: 3.10
- **环境路径**: `/opt/miniconda3/envs/tg-notion-bot`

### 重要：Conda 环境使用方式
由于 Claude Code 每次 Bash 命令在独立进程中执行，`conda activate` 无法持久生效。
**必须使用完整路径调用命令：**

```bash
# 安装依赖
/opt/miniconda3/envs/tg-notion-bot/bin/pip install <package>

# 运行 Python
/opt/miniconda3/envs/tg-notion-bot/bin/python main.py

# 查看已安装包
/opt/miniconda3/envs/tg-notion-bot/bin/pip list
```

### 依赖管理
项目有两个依赖文件，**必须同步更新**：
- `requirements.txt` - 本地开发环境
- `docker-requirements.txt` - Docker 生产环境

添加新依赖时：
1. 先在本地安装测试：`/opt/miniconda3/envs/tg-notion-bot/bin/pip install <package>`
2. 同时更新两个文件，保持版本一致
3. 注意版本约束，避免使用过于宽松的 `>=` 导致版本不一致

## 开发工作流

### 1. 创建 Issue
根据用户需求在 Linear 创建 Issue，包含：
- 问题描述
- 当前实现分析
- 建议解决方案
- 相关文件列表

### 2. 创建功能分支
```bash
git checkout -b feature/DEV-xxx-简短描述
```

分支命名规范：
- 功能：`feature/DEV-xxx-description`
- 修复：`fix/DEV-xxx-description`
- 紧急：`hotfix/DEV-xxx-description`

### 3. 更新 Issue 状态为 In Progress
```
mcp__plugin_linear_linear__update_issue
- id: Issue UUID
- state: "In Progress"
```

### 4. 本地开发和测试
```bash
# 安装/更新依赖
/opt/miniconda3/envs/tg-notion-bot/bin/pip install -r requirements.txt

# 运行测试
/opt/miniconda3/envs/tg-notion-bot/bin/python main.py
```

### 5. Docker 测试
```bash
# 构建并启动
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 如果修改了依赖，需要重新构建（不使用缓存）
docker-compose build --no-cache && docker-compose up -d
```

### 6. 提交代码
```bash
# 添加文件
git add <files>

# 提交（使用约定式提交格式）
git commit -m "feat(DEV-xxx): 功能描述

详细说明...

Co-Authored-By: Claude <noreply@anthropic.com>"
```

提交类型：
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构
- `docs`: 文档
- `chore`: 杂项

### 7. 合并到 main
```bash
git checkout main
git merge feature/DEV-xxx-description --no-ff -m "Merge branch 'feature/DEV-xxx-description' into main"
git push origin main
```

### 8. 清理分支
```bash
git branch -d feature/DEV-xxx-description
```

### 9. 更新 Issue 状态为 Done
```
mcp__plugin_linear_linear__update_issue
- id: Issue UUID
- state: "Done"
```

## 项目结构

```
tg_notion_bot/
├── main.py                 # 入口文件
├── config/                 # 配置模块
├── services/
│   ├── telegram_service/   # Telegram 相关服务
│   ├── notion_service/     # Notion 相关服务
│   ├── gemini_service/     # Gemini AI 服务
│   └── url_service.py      # URL 内容提取服务
├── utils/                  # 工具函数
├── requirements.txt        # 本地依赖
├── docker-requirements.txt # Docker 依赖
├── Dockerfile
├── docker-compose.yml
└── .env                    # 环境变量（不提交）
```

## 常见问题

### Docker 构建缓慢
如果修改了 `docker-requirements.txt`，Docker 会重新安装所有依赖。
优化方案：只在必要时修改依赖文件。

### Firecrawl 版本问题
firecrawl-py 2.x+ 版本 API 不兼容，必须锁定为 `>=1.0.0,<2.0.0`。

### 中文编码问题
使用 BeautifulSoup 时，需要正确处理编码：
```python
if response.encoding is None or response.encoding.lower() == 'iso-8859-1':
    response.encoding = response.apparent_encoding
soup = BeautifulSoup(response.content, "html.parser", from_encoding=response.encoding)
```
