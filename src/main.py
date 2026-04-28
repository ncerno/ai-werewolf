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


def _check_api_key(config: dict) -> None:
    """检查是否配置了 API Key，未配置则打印警告。"""
    llm = config.get("llm", {})
    default_key = llm.get("default", {}).get("api_key", "")
    god_key = llm.get("god_agent", {}).get("api_key", "")

    has_key = (default_key and default_key != "sk-placeholder") or \
              (god_key and god_key != "sk-placeholder")

    if not has_key:
        print("[WARN] LLM API Key 未配置！", file=sys.stderr)
        print("  请编辑 config/default.yaml 或设置环境变量 LLM_DEFAULT_API_KEY", file=sys.stderr)
        print("  否则启动游戏时 LLM 调用将失败。", file=sys.stderr)


def main():
    config = load_config()
    server = config.get("server", {})

    parser = argparse.ArgumentParser(description="AI 狼人杀")
    parser.add_argument("--host", default=server.get("host", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=server.get("port", 8000))
    parser.add_argument("--reload", action="store_true", default=server.get("reload", False))
    args = parser.parse_args()

    _check_api_key(config)

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