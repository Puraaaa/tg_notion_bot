#!/bin/bash

# 设置颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}启动 tg_notion_bot Docker 容器...${NC}"

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Docker 未运行，请先启动 Docker 服务${NC}"
    exit 1
fi

# 检查容器状态
if docker ps | grep -q "tg_notion_bot"; then
    echo -e "${YELLOW}tg_notion_bot 已经在运行中${NC}"
    echo -e "${YELLOW}当前容器状态:${NC}"
    docker ps | grep tg_notion_bot
    
    echo -e "${YELLOW}是否要重启容器? [y/N]${NC}"
    read -r restart_choice
    if [[ $restart_choice =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}重启容器...${NC}"
        docker-compose restart
    else
        echo -e "${YELLOW}查看容器日志:${NC}"
        docker-compose logs -f
        exit 0
    fi
else
    # 检查是否已经构建
    if docker images | grep -q "tg_notion_bot"; then
        echo -e "${YELLOW}找到镜像，启动容器...${NC}"
    else
        echo -e "${YELLOW}未找到镜像，开始构建...${NC}"
        if ! docker-compose build; then
            echo -e "${RED}构建失败，请查看上面的错误信息${NC}"
            exit 1
        fi
    fi
    
    # 启动容器
    echo -e "${YELLOW}创建并启动容器...${NC}"
    if ! docker-compose up -d; then
        echo -e "${RED}启动容器失败，请查看上面的错误信息${NC}"
        exit 1
    fi
fi

# 确认容器已启动
if docker ps | grep -q "tg_notion_bot"; then
    echo -e "${GREEN}容器已成功启动!${NC}"
    echo -e "${YELLOW}容器状态:${NC}"
    docker ps | grep tg_notion_bot
    
    echo -e "${YELLOW}查看日志输出? [Y/n]${NC}"
    read -r view_logs
    if [[ ! $view_logs =~ ^[Nn]$ ]]; then
        docker-compose logs -f
    fi
else
    echo -e "${RED}容器未能成功启动，请检查错误${NC}"
    docker-compose logs
    exit 1
fi
