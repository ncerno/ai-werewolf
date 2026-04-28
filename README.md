# AI 狼人杀 · 12 人局模拟器

全 LLM Agent 自动对决，支持旁观/上帝/玩家三种模式，Web 前端实时交互。

## 快速启动

```bash
# 1. 克隆项目
git clone https://github.com/ncerno/ai-werewolf.git
cd ai-werewolf

# 2. 安装依赖（Python 3.10+）
pip install -r requirements.txt

# 3. 配置 API Key（三选一）
# 方式 A: 编辑 config/default.yaml，填入 llm.default.api_key
# 方式 B: 复制 .env.example 为 .env，填入 LLM_DEFAULT_API_KEY
# 方式 C: 启动后在 Web 前端设置面板填入

# 4. 启动服务
python -m src.main

# 5. 打开浏览器访问 http://localhost:8000
```

## 三种模式

| 模式 | 说明 |
|------|------|
| **旁观模式** | 全 AI 自动对决，实时观看游戏过程 |
| **上帝模式** | 用户当上帝，为所有玩家做决策，操控游戏进程 |
| **玩家模式** | 人类扮演一个随机角色，其余 11 个由 AI 扮演 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `LLM_DEFAULT_API_KEY` | LLM API Key |
| `LLM_DEFAULT_API_BASE` | LLM API 地址（默认 DeepSeek） |
| `LLM_DEFAULT_MODEL` | LLM 模型名（默认 deepseek-chat） |
| `GOD_AGENT_API_KEY` | 上帝 Agent 的 API Key（可选） |

## 项目结构

```
src/
  engine/      游戏规则引擎（状态、规则、控制器）
  agent/        LLM Agent（玩家 Agent、上帝 Agent）
  server/       FastAPI 后端（API、WebSocket、序列化）
  frontend/     Web 前端（单文件 SPA）
  utils/        工具（配置、日志）
config/         默认配置文件
tests/          单元测试（101 项）
```

## 运行测试

```bash
python -m pytest tests/ -v
```