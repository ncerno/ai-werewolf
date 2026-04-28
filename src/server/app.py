"""FastAPI 应用主文件。"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..utils.config import PROJECT_ROOT, load_config
from .game_manager import GameManager
from .websocket import WebSocketManager


# ============================================================
# Pydantic 模型
# ============================================================

class GameStartRequest(BaseModel):
    mode: str = "auto"
    config: dict | None = None


# ============================================================
# 生命周期
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动
    ws_manager = WebSocketManager()
    game_manager = GameManager()
    game_manager.set_ws_manager(ws_manager)
    ws_manager.set_game_manager(game_manager)
    app.state.ws_manager = ws_manager
    app.state.game_manager = game_manager
    yield
    # 关闭
    if game_manager._status.value == "running":
        await game_manager.stop_game()


app = FastAPI(
    title="AI 狼人杀",
    description="全 LLM Agent 自动对决，支持旁观/上帝/玩家三种模式",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 前端静态文件
frontend_dir = PROJECT_ROOT / "src" / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ============================================================
# 基础路由
# ============================================================

@app.get("/")
async def root():
    return {"name": "AI 狼人杀", "version": "0.1.0", "status": "running"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/config/default")
async def get_default_config():
    """返回当前加载的完整配置（敏感字段脱敏）。"""
    config = load_config()
    _mask_api_keys(config)
    return config


# ============================================================
# 游戏 API
# ============================================================

@app.post("/api/game/start")
async def start_game(request: GameStartRequest):
    """启动新游戏。"""
    gm = app.state.game_manager
    return await gm.start_game(request.mode, request.config)


@app.post("/api/game/stop")
async def stop_game():
    """停止当前游戏。"""
    gm = app.state.game_manager
    return await gm.stop_game()


@app.get("/api/game/status")
async def get_game_status():
    """获取游戏状态。"""
    return app.state.game_manager.get_status()


@app.get("/api/game/state")
async def get_game_state():
    """获取当前游戏状态（旁观视角）。"""
    state = app.state.game_manager.get_serializable_state("spectator")
    status = app.state.game_manager.get_status()
    return {"status": status, "state": state}


# ============================================================
# WebSocket
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    ws_manager: WebSocketManager = app.state.ws_manager
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            await ws_manager.handle_client_message(websocket, raw)
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)


# ============================================================
# 辅助
# ============================================================

def _mask_api_keys(config: dict):
    """脱敏 API Key。"""
    llm = config.get("llm", {})
    for section in [llm.get("default", {})] + [
        v for v in llm.get("role_overrides", {}).values()
    ]:
        if section.get("api_key"):
            key = section["api_key"]
            if len(key) > 8:
                section["api_key"] = key[:4] + "****" + key[-4:]
    god = llm.get("god_agent", {})
    if god.get("api_key"):
        key = god["api_key"]
        if len(key) > 8:
            god["api_key"] = key[:4] + "****" + key[-4:]
