# 架构与契约 — 方案 P1

## 系统架构

### 架构图（文本描述）

```
┌─────────────────────────────────────────────────────┐
│                   用户浏览器                          │
│          (Jinja2 模板 + HTMX 交互增强)                │
└─────────────────────┬──────────────────────────────┘
                      │ HTTP / SSE
                      ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Web 服务                         │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ 路由层   │→ │ 业务逻辑  │→ │ LLM 客户端模块   │   │
│  │ Routes   │  │ Services │  │ (httpx + SSE)    │   │
│  └─────────┘  └──────────┘  └──────────────────┘   │
│       │                                            │
│       ▼                                            │
│  ┌─────────┐                                       │
│  │ 数据层   │                                       │
│  │ SQLite  │                                       │
│  └─────────┘                                       │
└─────────────────────────────────────────────────────┘
```

### 核心组件

| 组件 | 职责 | 技术实现 | 关键配置 |
|------|------|---------|---------|
| **路由层 (Routes)** | 处理 HTTP 请求路由、输入校验、模板渲染 | FastAPI + Pydantic | 路由前缀 `/api/` 和 `/{path}` 区分 API 与页面 |
| **鉴权中间件 (Auth)** | Session 鉴权，保护写入 API 端点 | starlette.middleware.sessions + 自定义依赖 | 写入 API 校验 `request.session`；公开页面跳过 |
| **业务逻辑层 (Services)** | 面试题管理、面试会话管理、评分逻辑 | 纯 Python 类 | 依赖注入到路由层 |
| **LLM 客户端模块 (LLM Client)** | 调用 LLM API 生成题目、模拟面试对话、评估答案 | httpx async + SSE | **MVP 默认 OpenAI**（`gpt-4o-mini`）；Anthropic / DeepSeek 适配器保留接口但为 Stub 实现，标记 Roadmap |
| **数据层 (Database)** | SQLite 持久化存储 | sqlite3 + 原生驱动 | 数据库路径由 `DATABASE_URL` 指定 |
| **模板引擎 (Templates)** | 服务器端渲染前端页面 | Jinja2 | 模板目录 `templates/` |
| **静态文件 (Static)** | CSS、JS 等静态资源 | FastAPI StaticFiles | 挂载 `/static` |

## 数据模型

### 核心实体

```
Entity: Question (面试题)
  - id: int [PK, auto-increment]
  - title: str [题目标题/问题]
  - category: str [题目分类: 技术/行为/系统设计/HR]
  - difficulty: str [难度级别: easy/medium/hard]
  - tags: str [标签, 逗号分隔]
  - expected_answer: str [参考答案/要点]
  - created_at: datetime [创建时间]
  - updated_at: datetime [更新时间]

Entity: InterviewSession (面试会话)
  - id: int [PK, auto-increment]
  - title: str [会话标题]
  - job_role: str [目标岗位]
  - status: str [状态: in_progress/completed/abandoned]
  - created_at: datetime [创建时间]
  - completed_at: datetime [完成时间]

Entity: InterviewQuestion (面试问答记录)
  - id: int [PK, auto-increment]
  - session_id: int [FK → InterviewSession.id]
  - question_id: int [FK → Question.id, nullable (如果是动态生成的)]
  - question_text: str [实际提问文本]
  - user_answer: str [用户回答, nullable]
  - ai_feedback: str [AI 反馈/评分, nullable]
  - score: float [评分, nullable, 0-100]
  - order_index: int [问题在会话中的序号]
  - created_at: datetime [创建时间]
  - answered_at: datetime [回答时间, nullable]

Entity: QuestionBank (题库)
  - id: int [PK, auto-increment]
  - name: str [题库名称]
  - description: str [题库描述]
  - created_at: datetime [创建时间]
```

## 数据库 Schema

```sql
-- 面试题表
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '技术',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    tags TEXT DEFAULT '',
    expected_answer TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 自动更新 updated_at 的触发器
CREATE TRIGGER IF NOT EXISTS trg_questions_updated_at
    AFTER UPDATE ON questions
    FOR EACH ROW
BEGIN
    UPDATE questions SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;

-- 面试会话表
CREATE TABLE IF NOT EXISTS interview_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    job_role TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 面试问答记录表
CREATE TABLE IF NOT EXISTS interview_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    question_id INTEGER,
    question_text TEXT NOT NULL,
    user_answer TEXT,
    ai_feedback TEXT,
    score REAL,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    answered_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES interview_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE SET NULL
);

-- 题库表
CREATE TABLE IF NOT EXISTS question_banks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_questions_category ON questions(category);
CREATE INDEX IF NOT EXISTS idx_questions_difficulty ON questions(difficulty);
CREATE INDEX IF NOT EXISTS idx_interview_questions_session ON interview_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_interview_sessions_status ON interview_sessions(status);
```

## API 接口契约

> **鉴权策略**：MVP 阶段使用简易 Session 鉴权。页面路由通过 FastAPI `SessionMiddleware` 校验 `request.session` 中的用户身份；API 写入端点（POST/PUT/DELETE）需要有效的 Session。`GET` 只读页面和 `/health` 跳过鉴权以便于健康检查。生产环境应升级为 JWT/OAuth2。

### 接口列表

| 方法 | 路径 | 描述 | 鉴权 | 备注 |
|------|------|------|------|------|
| GET | / | 首页仪表盘 | Session | — |
| GET | /questions | 题库列表页 | Session | — |
| GET | /questions/{id} | 题目详情页 | Session | — |
| GET | /questions/new | 新增题目页面 | Session | — |
| GET | /questions/{id}/edit | 编辑题目页面 | Session | — |
| POST | /api/questions | 创建题目 | Session | 写入 API 全部校验 Session |
| PUT | /api/questions/{id} | 更新题目 | Session | — |
| DELETE | /api/questions/{id} | 删除题目 | Session | — |
| GET | /api/questions | 获取题目列表（支持分页/搜索/过滤） | Session | — |
| POST | /api/questions/generate | AI 生成题目 | Session | 消耗 LLM 配额 |
| GET | /sessions | 面试会话列表页 | Session | — |
| GET | /sessions/new | 新建面试会话页面 | Session | — |
| GET | /sessions/{id} | 面试会话详情/进行页 | Session | — |
| POST | /api/sessions | 创建面试会话 | Session | — |
| POST | /api/sessions/{id}/start | 开始面试 | Session | — |
| POST | /api/sessions/{id}/answer | 提交答案并获取下个问题 | Session | — |
| GET | /api/sessions/{id}/stream | SSE 流式面试对话 | Session | — |
| POST | /api/sessions/{id}/complete | 结束面试 | Session | — |
| GET | /api/sessions/{id}/review | 面试回顾/评分页 | Session | — |
| GET | /banks | 题库管理页 | Session | — |
| GET | /api/banks | 获取题库列表 | Session | — |
| POST | /api/banks | 创建题库 | Session | — |
| POST | /api/banks/{id}/import | 导入题目到题库 | Session | — |
| DELETE | /api/banks/{id} | 删除题库 | Session | — |
| GET | /health | 健康检查 | 无 | 跳过鉴权，供负载均衡器使用 |

### 接口详情

#### `POST /api/questions/generate`

**请求：**
```json
{
    "category": "技术",
    "difficulty": "medium",
    "count": 5,
    "topic": "Python 异步编程",
    "language": "zh"
}
```

**响应（200）：**
```json
{
    "questions": [
        {
            "title": "请解释 Python 中 async/await 的工作原理",
            "category": "技术",
            "difficulty": "medium",
            "tags": "Python,异步,协程",
            "expected_answer": "async/await 基于协程实现..."
        }
    ]
}
```

#### `POST /api/sessions/{id}/answer`

**请求：**
```json
{
    "question_id": 1,
    "user_answer": "async/await 是 Python 3.5 引入的异步编程语法..."
}
```

**响应（200，非流式模式）：**
```json
{
    "feedback": "你的回答覆盖了基本概念，但遗漏了事件循环的细节...",
    "score": 75,
    "next_question": {
        "id": 2,
        "question_text": "asyncio.gather 和 asyncio.create_task 有什么区别？"
    },
    "session_completed": false
}
```

**错误响应：**

| 状态码 | 场景 | 响应体 |
|--------|------|--------|
| 400 | 请求参数校验失败 | `{"detail": "字段 'user_answer' 不能为空"}` |
| 404 | 面试会话不存在 | `{"detail": "会话未找到"}` |
| 409 | 会话已结束 | `{"detail": "该面试会话已结束，无法继续作答"}` |
| 500 | LLM API 调用失败 | `{"detail": "AI 服务暂时不可用，请稍后重试"}` |

#### `GET /api/sessions/{id}/stream`（SSE 流式面试）

**响应（200，text/event-stream）：**
```
data: {"type": "question", "content": "请解释 Python 中 async/await 的工作原理"}

data: {"type": "thinking", "content": "等待用户回答..."}

data: {"type": "feedback", "content": "你的回答覆盖了基本概念..."}

data: {"type": "score", "content": "75"}

data: {"type": "next", "content": "asyncio.gather 和 asyncio.create_task 有什么区别？"}

data: {"type": "done", "content": ""}
```

#### `GET /health`

**响应（200）：**
```json
{
    "status": "ok",
    "version": "1.0.0",
    "database": "connected",
    "llm_provider": "openai"
}
```

---

## 演进路径（Evolution Path）

> 本节定义从 MVP 到生产环境的渐进式演进路线，确保技术债可控、迁移路径清晰。

### Phase 1：MVP（本方案，1 周交付）

| 维度 | 当前选择 | 天花板 |
|------|---------|--------|
| 数据库 | SQLite 单文件 | 10GB / 单机并发写入 < 1000 QPS |
| 鉴权 | 简易 Session 鉴权 | 单用户 / 小团队 |
| LLM Provider | 仅 OpenAI（保留接口） | 单一提供商 |
| 部署 | 单实例 Uvicorn | 单机 CPU/内存 |
| 前端 | Jinja2 + HTMX | 服务器渲染 |

### Phase 2：多用户协作（触发条件：≥5 用户或需要权限分级）

| 变更项 | 目标方案 | 工作量预估 | 向后兼容 |
|--------|---------|-----------|---------|
| 数据库 → PostgreSQL | SQLite → PostgreSQL（使用 SQLAlchemy 抽象层） | 2-3 天 | 提供数据迁移脚本 |
| 鉴权 → JWT | Session → JWT + OAuth2（FastAPI 内置支持） | 1-2 天 | Session 与 JWT 可并行 |
| 会话共享 → Redis | 引入 Redis 存储 Session 和缓存 | 1 天 | 渐进式接入 |

### Phase 3：生产就绪（触发条件：需要高可用或性能瓶颈）

| 变更项 | 目标方案 | 工作量预估 | 向后兼容 |
|--------|---------|-----------|---------|
| 水平扩展 | 多实例 + Nginx 负载均衡 | 1-2 天 | 无代码变更 |
| LLM 多 Provider | OpenAI + Anthropic + DeepSeek 适配器全量实现 | 2-3 天 | 接口不变，新增 Provider 配置即可 |
| 日志系统 | 接入 structlog + 日志聚合（ELK / Loki） | 1-2 天 | 渐进式替换 |
| 对象存储 | SQLite 文件存储 → S3/MinIO（附件/导出） | 1-2 天 | 可选能力 |
| Rate Limiting | 接入 slowapi 或自定义中间件 | 0.5 天 | 无侵入 |

### 不升级的替代方案

对于部分场景，不升级架构也可通过以下方式缓解：
- **SQLite 并发瓶颈**：使用 `WAL` 模式 + 连接池 + 读写分离（只读副本），可将承受能力提升到 QPS ~5000
- **数据量超限**：定期归档历史数据到独立 SQLite 文件或 CSV