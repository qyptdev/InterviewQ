# Contributing to InterviewQ

首先，感谢你考虑为 InterviewQ 做贡献！🎉

## 如何贡献

### 报告 Bug

1. 在 [GitHub Issues](../../issues) 中搜索是否已有类似问题
2. 如果没有，新建 Issue，包含：
   - 问题描述与复现步骤
   - 预期行为 vs 实际行为
   - 运行环境（Python 版本、OS 等）
   - 相关日志/截图

### 提交功能建议

1. 在 Issues 中创建 Feature Request
2. 描述使用场景、期望行为、为什么现有功能不满足

### 提交代码

1. **Fork** 本仓库
2. 创建功能分支：`git checkout -b feat/your-feature-name`
3. 编写代码并添加测试
4. 确保所有测试通过：`python -m pytest tests/ -v`
5. 提交时使用清晰的 commit message：
   - `feat: 添加 XXX 功能`
   - `fix: 修复 XXX 问题`
   - `docs: 更新 XXX 文档`
   - `refactor: 重构 XXX 模块`
6. 推送到 Fork 并创建 Pull Request

### 开发环境搭建

```bash
# 1. Clone & venv
git clone https://github.com/<your-username>/InterviewQ.git
cd InterviewQ
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# 编辑 .env 配置 LLM API

# 4. Run tests
python -m pytest tests/ -v
```

## 代码规范

- **Python 风格**：遵循 PEP 8，使用 `ruff` 格式化
- **类型标注**：所有函数签名应包含类型标注
- **文档字符串**：公共函数和类需包含 docstring
- **测试**：新功能需附带测试用例
- **中文注释**：业务逻辑注释可使用中文

## Pull Request 检查清单

- [ ] 代码通过 `ruff check` 和 `ruff format`
- [ ] 新功能附带测试
- [ ] 所有现有测试通过
- [ ] 更新了相关文档（如适用）
- [ ] commit message 遵循约定格式

## 许可证

提交代码即表示你同意在 Apache License 2.0 下授权你的贡献。
