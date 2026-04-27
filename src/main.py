"""AI 狼人杀 · FastAPI 启动入口。

Usage:
    python -m src.main              # 启动服务
    python -m src.main --port 9000  # 指定端口
    python -m src.main --reload     # 开发模式自动重载
"""
import argparse
import sys
from pathlib import Path

import uvicorn

from .utils.config import PROJECT_ROOT, load_config


def main():
    config = load_config()
    server = config.get("server", {})

    parser = argparse.ArgumentParser(description="AI 狼人杀")
    parser.add_argument("--host", default=server.get("host", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=server.get("port", 8000))
    parser.add_argument("--reload", action="store_true", default=server.get("reload", False))
    args = parser.parse_args()

    print("=" * 60)
    print("  AI 狼人杀 · 12 人局模拟器")
    print(f"  启动地址: http://{args.host}:{args.port}")
    print("=" * 60)

    uvicorn.run(
        "src.server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
