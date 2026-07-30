# 使用 Python 3.11 作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=8 \
    GUNICORN_TIMEOUT=120 \
    SCHEDULER_STANDALONE=true

# 复制依赖文件
COPY requirements.txt .

# 安装依赖（pip 走国内镜像加速）
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install gunicorn -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data && chmod +x /app/scripts/start-gunicorn.sh

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python","-c","import urllib.request as u; u.urlopen('http://localhost:5000/healthz', timeout=4).read()"]

# 启动应用：默认独立 scheduler + 2 workers + 多线程（Issue #69 Phase 4）
# start 脚本在 SCHEDULER_STANDALONE=true 时拉起 sibling scheduler 进程
# 回退：SCHEDULER_STANDALONE=false 且 GUNICORN_WORKERS=1
# 注意：禁用 --preload，避免在 master 进程中启动后台调度线程
CMD ["scripts/start-gunicorn.sh"]
