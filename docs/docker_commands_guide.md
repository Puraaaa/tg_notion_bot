# Docker 命令使用指南

## Docker Compose 常用命令解释

Docker Compose 命令有不同的作用，理解它们的区别很重要：

### 全流程更新命令（推荐用于更新部署）

```
# 全流程更新命令（推荐用于更新部署）
docker compose pull && docker compose up -d --build
```

### 构建相关命令

- **`docker-compose build`**: 仅构建镜像，不创建或启动容器
  ```bash
  # 构建镜像
  docker-compose build

  # 不使用缓存重新构建镜像
  docker-compose build --no-cache
  ```

### 启动相关命令

- **`docker-compose up`**: 创建并启动容器（前台运行）

  ```bash
  # 创建并启动容器，显示日志输出
  docker-compose up

  # 创建并启动容器，后台运行
  docker-compose up -d
  ```
- **`docker-compose start`**: 启动已创建的容器

  ```bash
  # 启动之前已创建但已停止的容器
  docker-compose start
  ```

### 停止相关命令

- **`docker-compose stop`**: 停止容器但不删除

  ```bash
  # 停止容器
  docker-compose stop
  ```
- **`docker-compose down`**: 停止并删除容器

  ```bash
  # 停止并删除容器、网络
  docker-compose down

  # 停止并删除容器、网络、镜像
  docker-compose down --rmi all
  ```

### 查看状态命令

- **`docker-compose ps`**: 查看容器状态

  ```bash
  # 查看所有容器状态
  docker-compose ps
  ```
- **`docker-compose logs`**: 查看容器日志

  ```bash
  # 查看日志
  docker-compose logs

  # 实时查看日志
  docker-compose logs -f
  ```

## 当前状态检查

要检查 `tg_notion_bot` 是否已经在运行，可以使用以下命令：

```bash
# 检查所有容器状态（包括未运行的）
docker ps -a | grep tg_notion_bot

# 只查看正在运行的容器
docker ps | grep tg_notion_bot
```

如果容器已经在运行，会显示容器信息。如果没有输出，则表示容器尚未运行。

## 启动应用程序

如果您已经完成了构建步骤，接下来需要启动容器：

```bash
# 使用docker-compose启动（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f
```

或者使用项目提供的启动脚本：

```bash
# 确保脚本有执行权限
chmod +x start.sh

# 运行启动脚本
./start.sh
```

## 完整工作流程

一个完整的重新构建和启动流程应该是：

```bash
# 停止并移除现有容器
docker-compose down

# 重新构建镜像（不使用缓存）
docker-compose build --no-cache

# 创建并启动新容器
docker-compose up -d

# 查看日志
docker-compose logs -f
```
