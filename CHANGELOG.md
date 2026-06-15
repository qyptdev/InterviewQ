# Changelog

本项目的所有重要变更均记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-06-15

### Added

- 智能面试题库生成：基于简历 + JD 的 AI 驱动出题（快速/标准/深度三种模式）
- Plan-Execute Agent 流水线：自动规划 → 批量出题 → 验证 → 补充
- 混合 RAG 检索引擎：BM25 + RAPTOR 树 + 向量检索三路召回
- 题库管理：批量生成、分类管理、难度标注、收藏去重
- 模拟面试双模式：对话式实时面试 + 卡片式练习
- 卡片模式计时 UI：独立计时、切题暂停续时、友好时间格式
- 流式 AI 评分反馈：实时输出评分与详细点评
- 简历解析：PDF / DOCX 上传，自动提取关键信息
- LLM 多模型路由：支持主模型（复杂任务）、轻量模型（简单任务）独立配置
- Embedding 模型支持：用于 RAG 向量检索
- Docker 一键部署：Dockerfile + docker-compose.yml
- 健康检查端点：`/health`
- 响应式 Web 界面：Tailwind CSS + HTMX 服务端渲染

### Technical

- Python 3.12 + FastAPI 0.136.x
- SQLite WAL mode + 原始 DAO 模式
- Pydantic BaseSettings 配置管理
- SSE (Server-Sent Events) 流式通信
- jieba 中文分词（题目去重）
