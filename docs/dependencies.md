# 依赖清单 — 方案 P1

## 运行时依赖

| 包名 | 版本 | 用途 | 许可协议 |
|------|------|------|---------|
| fastapi | >=0.110.0, <0.137.0 | Web 框架，异步 API 服务 | MIT |
| uvicorn | >=0.29.0, <0.34.0 | ASGI 服务器，运行 FastAPI | BSD-3-Clause |
| sqlite3 | Python 标准库 | 嵌入式关系数据库（零配置持久化） | Python Software Foundation |
| jinja2 | >=3.1.0, <4.0.0 | 模板引擎，渲染前端页面 | BSD-3-Clause |
| httpx | >=0.27.0, <0.29.0 | HTTP 客户端，调用 LLM API | BSD-3-Clause |
| python-dotenv | >=1.0.0, <2.0.0 | 环境变量加载 | BSD-3-Clause |
| pydantic | >=2.5.0, <3.0.0 | 数据校验与设置管理 | MIT |
| python-multipart | >=0.0.9, <0.1.0 | 表单数据解析（用于搜索/过滤等表单提交） | Apache-2.0 |
| sse-starlette | >=2.0.0, <3.0.0 | Server-Sent Events 支持（LLM 流式输出） | MIT |

## 开发依赖

| 包名 | 版本 | 用途 | 许可协议 |
|------|------|------|---------|
| pytest | >=8.0.0, <9.0.0 | 测试框架 | MIT |
| pytest-asyncio | >=0.23.0, <1.0.0 | FastAPI 异步测试支持 | Apache-2.0 |
| black | >=24.0.0, <25.0.0 | 代码格式化 | MIT |
| ruff | >=0.3.0, <1.0.0 | linter | MIT |
| mypy | >=1.8.0, <2.0.0 | 静态类型检查 | MIT |

## 锁文件示例

### requirements.txt

```txt
fastapi==0.136.3
uvicorn[standard]==0.34.0
jinja2==3.1.6
httpx==0.28.1
python-dotenv==1.1.0
pydantic==2.11.1
python-multipart==0.0.20
sse-starlette==2.2.1
```

### requirements-dev.txt

```txt
pytest==8.3.5
pytest-asyncio==0.25.3
black==25.1.0
ruff==0.9.10
mypy==1.15.0
```

## 版本选择说明

| 包名 | 选定版本 | 选择理由 | 兼容风险 |
|------|---------|---------|---------|
| fastapi | 0.136.x | 最新稳定版，含 Pydantic v2 全部特性 | 无已知兼容风险 |
| uvicorn | 0.34.x | 最新 ASGI 服务器，支持 HTTP/2 | 需要 Python >=3.9 |
| jinja2 | 3.1.x | FastAPI 官方集成推荐版本 | 需要 MarkupSafe >=2.0 |
| httpx | 0.28.x | 支持 async/await，LLM API 调用原生适配 | 需关注 httpx 0.29+ 的 API 变化 |
| sse-starlette | 2.2.x | 最小化 SSE 集成，与 FastAPI 原生兼容 | 需要 Starlette >=0.30 |