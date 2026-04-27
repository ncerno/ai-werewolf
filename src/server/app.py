"""FastAPI 应用主文件。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from ..utils.config import PROJECT_ROOT, load_config

app = FastAPI(
    title="AI 狼人杀",
    description="全 LLM Agent 自动对决，支持旁观/上帝/玩家三种模式",
    version="0.1.0",
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
