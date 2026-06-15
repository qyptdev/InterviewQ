# InterviewQ

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-009688.svg)](https://fastapi.tiangolo.com/)

AI 驱动的智能面试题库生成与模拟面试平台。支持基于简历/职位描述的智能出题、批量管理、模拟面试（对话式 & 卡片式）、AI 实时评分与反馈。

## ✨ 功能特性

- **🧠 智能出题**：基于简历和岗位描述（JD），通过 Plan-Execute Agent 流水线自动生成高质量面试题
- **📚 题库管理**：批量生成、分类管理、难度标注、收藏去重
- **🎯 模拟面试**：对话式 & 卡片式双模式，支持计时、追问、暂停续时
- **📊 AI 评分反馈**：流式输出实时评分，含详细点评与改进建议
- **📄 简历解析**：支持 PDF / DOCX 上传，自动提取关键信息驱动出题
- **🔍 混合 RAG**：BM25 + RAPTOR 树 + 向量检索三路召回，确保题目准确性
- **🐳 一键部署**：Docker Compose 一行命令启动

## 技术栈

| 层级 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI 0.136.x |
| 数据库 | SQLite (WAL mode) |
| 模板引擎 | Jinja2 + HTMX (SSR) |
| LLM 客户端 | httpx (async, OpenAI-compatible API, streaming) |
| Agent 流水线 | 自研 Plan-Execute 模式 (纯 Python) |
| RAG | 混合检索 (BM25 + RAPTOR + Vector) |
| 中文 NLP | jieba |
| 文档解析 | PyMuPDF (PDF) + python-docx (DOCX) |
| 实时通信 | SSE (sse-starlette) |

## 项目结构

```
InterviewQ/
├── app/                          # Application code
│   ├── main.py                   # FastAPI entry point
│   ├── config.py                 # Pydantic BaseSettings
│   ├── database.py               # SQLite connection & init
│   ├── api/                      # REST API routes
│   ├── core/                     # Agent orchestration (Plan-Execute pipeline)
│   ├── rag/                      # Hybrid RAG engine (BM25 + RAPTOR + Vector)
│   ├── llm/                      # LLM client layer
│   ├── services/                 # Business logic
│   ├── models/                   # Data models (Pydantic + DAO)
│   ├── templates/                # Jinja2 HTML templates
│   └── static/                   # CSS, JS, images
├── prompts/                      # LLM prompt templates
├── tests/                        # Test suite
├── docs/                         # Documentation
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your LLM API configuration
# Required: LLM_PRIMARY_BASE_URL, LLM_PRIMARY_API_KEY, LLM_PRIMARY_MODEL
# Optional: LLM_LIGHT_*, LLM_EMBEDDING_* (for RAG vector search)

# 4. Initialize database
python -c "from app.database import init_db; init_db()"

# 5. Start server
uvicorn app.main:app --reload --port 8000

# 6. Open browser
# http://localhost:8000
```

## Docker

```bash
docker compose up -d
```

## 使用方式

1. **上传简历**：在 Resume 页面上传 PDF/DOCX 简历 + 填写目标岗位
2. **生成题库**：选择出题模式（快速/标准/深度），AI 将基于简历内容生成面试题
3. **管理题库**：在 Banks 页面对题目进行分类、编辑、收藏、删除
4. **模拟面试**：创建 Session，选择对话式或卡片式进行练习
5. **查看反馈**：面试结束后查看每题评分和详细点评

## 环境变量配置

参见 `.env.example` 获取完整配置模板。核心配置项：

| 变量 | 说明 | 必需 |
|------|------|------|
| `LLM_PRIMARY_BASE_URL` | 主 LLM API 地址 | ✅ |
| `LLM_PRIMARY_API_KEY` | 主 LLM API 密钥 | ✅ |
| `LLM_PRIMARY_MODEL` | 主 LLM 模型名称 | ✅ |
| `LLM_LIGHT_*` | 轻量 LLM 配置（简单任务） | ❌ |
| `LLM_EMBEDDING_*` | Embedding 模型配置（RAG 向量检索） | ❌ |
| `APP_SECRET_KEY` | 应用密钥（生产环境必须设置） | ⚠️ |
| `DATABASE_URL` | 数据库连接字符串 | ❌ |

## Contributing

欢迎贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

## License

本项目基于 [Apache License 2.0](LICENSE) 开源。

Copyright 2026 InterviewQ Contributors
