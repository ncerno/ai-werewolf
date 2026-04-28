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

## 配置指南

### API Key

项目使用 OpenAI 兼容接口，默认指向 DeepSeek API。API Key 可通过三种方式配置（优先级由高到低）：

| 优先级 | 方式 | 说明 |
|--------|------|------|
| 1 | 环境变量 | `LLM_DEFAULT_API_KEY`，启动前 `export` 或写入 `.env` |
| 2 | 配置文件 | `config/default.yaml` 中 `llm.default.api_key` |
| 3 | 前端设置 | 启动后在设置面板填入，保存到浏览器 localStorage |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_DEFAULT_API_KEY` | LLM API Key（必填） | - |
| `LLM_DEFAULT_API_BASE` | LLM API 地址 | `https://api.deepseek.com/v1` |
| `LLM_DEFAULT_MODEL` | LLM 模型名 | `deepseek-chat` |
| `GOD_AGENT_API_KEY` | 上帝 Agent 的 API Key（可选，默认复用 default） | - |

也可直接编辑 `config/default.yaml` 修改模型、温度、token 数等参数。

### 多模型模式

`config/default.yaml` 中 `llm.role_overrides` 可为每种角色指定独立的模型和 API Key。将对应角色的 `enabled` 设为 `true` 并填入配置即可。狼人用 GPT-4、村民用 DeepSeek 等组合均可支持。

### 启动参数

```
python -m src.main                        # 默认启动（0.0.0.0:8000）
python -m src.main --port 9000            # 指定端口
python -m src.main --host 127.0.0.1       # 仅本地访问
python -m src.main --reload               # 开发模式，代码变更自动重启
```

## 三种模式

### 旁观模式（Auto）

全 AI 自动对决。用户纯观看，不参与决策。

操作：选择"旁观模式" → 点击"开始游戏" → 观察 12 个 AI Agent 自主进行狼人杀对决。

### 上帝模式（God）

用户扮演上帝，为所有 12 名玩家做决策。每一步游戏行动（狼人选刀、预言家查验、女巫用药、白天发言、投票放逐等）都会弹出决策面板，由你来选择目标和内容。

操作：
1. 选择"上帝模式" → 点击"开始游戏"
2. 状态栏出现红色断开时等待决策面板弹出
3. 选择目标玩家（点击数字圆圈）或输入发言内容
4. 点击"确认"提交决策，游戏继续
5. 轮到下一个玩家时重复步骤 2-4

注意：女巫用药时，先点击"使用解药/使用毒药/跳过"，选毒药后才出现目标选择器，选解药或跳过会自动提交。

### 玩家模式（Player）

人类扮演一个随机角色，其余 11 名由 AI 扮演。你只能看到自己的身份牌，死亡玩家的身份会公开。轮到你的回合时弹出决策面板，其他玩家的回合由 AI 自动执行。

操作：
1. 选择"玩家模式" → 点击"开始游戏"
2. 游戏初始化后，日志区会显示你的身份
3. 轮到你的回合时，决策面板弹出
4. 做出选择后点击"确认"
5. 等待 AI 玩家行动，观察局势发展
6. 如果你死亡，视角自动切换为旁观模式

## 前端界面

```
┌─────────────────────────────────────┐
│  状态栏  回合3  存活9  ● 已连接  [停止] │
├─────────────────────────────────────┤
│                                     │
│      ●1号    ●2号    ●3号    ●4号     │
│       狼      预      巫      猎      │
│                                     │
│      ●5号    ●6号    ●7号    ●8号     │
│       民      民      狼      民      │
│                                     │
│      ●9号   ☆10号   ✝11号   ✝12号    │
│       民      狼      狼      痴      │
│                                     │
├─────────────────────────────────────┤
│  决策面板（God/Player 模式弹出）        │
│  10号 (狼) - 击杀目标                 │
│  [●1] [●2] [●3] ... [确认] [跳过]    │
├─────────────────────────────────────┤
│  日志区                              │
│  --- 第 3 夜 ---                     │
│  狼人决定击杀 3 号                     │
│  天亮了，昨夜 3 号玩家死亡              │
│  1 号发言：我是预言家...               │
└─────────────────────────────────────┘
```

**状态指示**：状态栏左侧圆点 —— 绿色已连接，红色断开（自动重连）。

**玩家卡片**：绿色边框=存活，红色边框+划线=死亡，金色边框+星徽=警长，蓝色脉冲=正在发言。

## 项目结构

```
ai-werewolf/
├── config/
│   └── default.yaml          # 默认配置（LLM、游戏参数、服务器）
├── src/
│   ├── main.py               # CLI 入口，uvicorn 启动
│   ├── engine/                # 游戏规则引擎
│   │   ├── state.py           #   Role/Phase 枚举，Player/GameState 数据类
│   │   ├── rules.py           #   胜利判定、行动校验、计票、狼人投票
│   │   └── controller.py      #   游戏主循环、夜晚/白天阶段调度
│   ├── agent/                 # LLM Agent 层
│   │   ├── parser.py          #   LLM 输出解析（正则提取 + 随机兜底）
│   │   ├── prompts.py         #   6 种角色系统提示词模板
│   │   ├── player.py          #   PlayerAgent：决策、发言、记忆压缩
│   │   └── god_agent.py       #   GodAgent：叙述事件、引导人类行动
│   ├── server/                # FastAPI 后端
│   │   ├── app.py             #   FastAPI 应用 + CORS + API 路由
│   │   ├── websocket.py       #   WebSocket 连接管理、命令路由
│   │   ├── game_manager.py    #   游戏生命周期管理、后台 asyncio.Task
│   │   └── serializer.py      #   状态序列化（三种视角）
│   ├── frontend/
│   │   └── index.html         # Web 前端 SPA（单文件，~1050 行）
│   └── utils/
│       ├── config.py          #   配置加载（YAML + 环境变量 + deep merge）
│       └── logger.py          #   日志系统
├── tests/                     # 单元测试（101 项）
├── docs/                      # 开发文档
├── data/                      # 运行时数据（日志、用户配置）
├── requirements.txt
├── .env.example
└── README.md
```

## 运行测试

```bash
python -m pytest tests/ -v
```

## 常见问题

**Q: 启动后打开浏览器看到错误页面？**
A: 检查是否配置了 API Key。启动时终端会打印 `[WARN]` 提示。未配置 Key 时服务仍可启动，但启动游戏后 LLM 调用会失败。

**Q: 上帝模式/玩家模式点击确认后没反应？**
A: WebSocket 断开了。检查状态栏圆点是否为绿色，红色表示连接断开，等待自动重连或刷新页面。

**Q: 如何修改游戏参数（人数、角色数量、发言时间等）？**
A: 编辑 `config/default.yaml` 中 `game` 和 `roles` 部分。

**Q: 支持哪些 LLM 提供商？**
A: 任何 OpenAI 兼容接口均可。修改 `api_base` 指向对应服务地址即可（如 OpenAI、DeepSeek、Ollama 本地模型等）。

**Q: 如何查看历史游戏记录？**
A: 游戏日志保存在 `data/game_logs/` 目录下（需 `config/default.yaml` 中 `output.save_log: true`）。