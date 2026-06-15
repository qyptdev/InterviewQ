# 环境与部署配置 — 方案 P1

## 环境变量模板

### .env.example

```env
# 应用配置
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
APP_SECRET_KEY=change-me-to-a-random-string-in-production

# 日志配置
LOG_LEVEL=INFO
LOG_FORMAT=default  # default 或 json（生产环境建议 json）

# Rate Limiting（可选，防止 LLM API 超支）
RATE_LIMIT_ENABLED=false
RATE_LIMIT_PER_MINUTE=30

# LLM API 配置
# 选择一种 LLM 后端，取消注释对应配置

# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_MODEL=gpt-4o-mini

# Anthropic Claude
# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key
# ANTHROPIC_MODEL=claude-sonnet-4-6

# 国内大模型（以 DeepSeek 为例）
# LLM_PROVIDER=deepseek
# DEEPSEEK_API_KEY=sk-your-deepseek-api-key
# DEEPSEEK_MODEL=deepseek-chat

# LLM 通用参数
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2048

# 数据库（SQLite 无需额外配置，默认使用项目目录下的文件）
DATABASE_URL=sqlite:///./data/interview.db

# 会话配置
SESSION_SECRET_KEY=change-me-in-production
SESSION_EXPIRE_HOURS=24

# 日志配置
LOG_LEVEL=INFO
LOG_FORMAT=default  # default 或 json（生产环境建议 json）

# Rate Limiting（可选，防止 LLM API 超支）
RATE_LIMIT_ENABLED=false
RATE_LIMIT_PER_MINUTE=30
```

## Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY ./app ./app
COPY ./templates ./templates
COPY ./static ./static
COPY .env.example .env

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8000

# 启动
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## docker-compose.yml

```yaml
version: "3.9"

services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
    environment:
      - APP_ENV=production
      - APP_HOST=0.0.0.0
      - APP_PORT=8000
    restart: unless-stopped
```

## CI/CD 流水线

### GitHub Actions 示例

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      - name: Lint with ruff
        run: ruff check .
      - name: Type check with mypy
        run: mypy app/
      - name: Test with pytest
        run: pytest -v
      - name: Build Docker image
        run: docker build -t interview-agent .
```

## 部署检查清单

- [ ] `.env` 中的 `APP_SECRET_KEY` 已替换为随机字符串（`openssl rand -hex 32` 生成）
- [ ] `SESSION_SECRET_KEY` 已替换为随机字符串
- [ ] LLM API 密钥已配置且余额充足
- [ ] `APP_ENV` 设置为 `production`
- [ ] 数据库文件目录（`./data/`）已创建且可读写
- [ ] 生产环境中使用 gunicorn + uvicorn workers 运行（`gunicorn -w 4 -k uvicorn.workers.UvicornWorker app.main:app`）
- [ ] 健康检查端点已确认可访问（`curl http://localhost:8000/health`）
- [ ] 若使用 Docker，数据卷已挂载（`-v ./data:/app/data`）
- [ ] SSL 证书已配置（推荐使用 Caddy 自动 HTTPS 或 Nginx + Let's Encrypt）
- [ ] 日志级别设置为 `INFO`（生产环境建议开启 JSON 格式）
- [ ] Rate Limiting 已评估是否启用
- [ ] 数据库备份策略已建立（cron 定时备份 `sqlite3 .backup`）