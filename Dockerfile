# 使用官方Python镜像作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 先复制requirements文件，利用Docker层缓存
COPY docker-requirements.txt .

# 安装依赖 - 使用国内镜像源加速
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    -r docker-requirements.txt && \
    # 验证安装
    python -c "import socks; import pyzotero; print('Dependencies installed successfully')"

# 复制项目文件
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai
ENV PYTHONWARNINGS="ignore:Unverified HTTPS request"

# 创建日志目录
RUN mkdir -p /app/logs

# 添加可执行权限到启动脚本
RUN chmod +x /app/start.sh

# 运行应用
CMD ["/app/start.sh"]
