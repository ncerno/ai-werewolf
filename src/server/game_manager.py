"""游戏管理器：游戏生命周期管理（创建、启动、停止），连接 GameController 与 WebSocket。"""
from __future__ import annotations

import asyncio
import traceback
from enum import Enum

from ..engine.controller import GameController
from ..engine.state import GameState
from .serializer import serialize_game_state


class GameStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    FINISHED = "finished"


class GameManager:
    """管理单局游戏的生命周期。

    包装 GameController，负责：
    - 创建游戏实例并在后台运行
    - 将 GameController._emit 事件桥接到 WebSocket
    - 暴露状态供 HTTP API 查询
    """

    def __init__(self):
        self._controller: GameController | None = None
        self._task: asyncio.Task | None = None
        self._ws_manager = None       # WebSocketManager，由 app.py 注入
        self._status: GameStatus = GameStatus.IDLE
        self._mode: str = "auto"
        self._config: dict = {}
        self._error: str | None = None

    # ============================================================
    # 依赖注入
    # ============================================================

    def set_ws_manager(self, ws_manager) -> None:
        self._ws_manager = ws_manager

    # ============================================================
    # 公共 API
    # ============================================================

    async def start_game(self, mode: str = "auto", config: dict | None = None) -> dict:
        """启动新游戏。如果已有游戏在运行则返回错误。"""
        if self._status == GameStatus.RUNNING:
            return {"success": False, "message": "已有游戏在运行中"}

        self._mode = mode
        self._config = config or {}
        self._error = None

        self._controller = GameController()
        self._controller.init_game(mode, self._config)

        self._status = GameStatus.RUNNING
        self._task = asyncio.create_task(self._wrap_run())

        return {
            "success": True,
            "mode": mode,
            "message": "游戏已启动",
        }

    async def stop_game(self) -> dict:
        """停止当前游戏。"""
        if self._status != GameStatus.RUNNING:
            return {"success": False, "message": "没有运行中的游戏"}

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._status = GameStatus.IDLE
        self._controller = None

        return {"success": True, "message": "游戏已停止"}

    def get_status(self) -> dict:
        """返回当前游戏状态摘要。"""
        state = self._controller.state if self._controller else None
        return {
            "status": self._status.value,
            "mode": self._mode,
            "turn": state.turn if state else 0,
            "phase": state.phase.name if state else "",
            "phase_name": _get_phase_label(state.phase) if state else "",
            "error": self._error,
        }

    def get_state(self) -> GameState | None:
        """返回原始 GameState 对象。"""
        if self._controller:
            return self._controller.state
        return None

    def get_serializable_state(self, perspective: str = "spectator") -> dict | None:
        """返回 JSON 安全的游戏状态。"""
        state = self.get_state()
        if state is None:
            return None
        return serialize_game_state(state, perspective)

    # ============================================================
    # 内部
    # ============================================================

    async def _wrap_run(self):
        """包装 controller.run()，处理完成和异常。"""
        try:
            await self._controller.run(self._event_callback)
            self._status = GameStatus.FINISHED
            self._broadcast_game_over()
        except asyncio.CancelledError:
            self._status = GameStatus.IDLE
            if self._ws_manager:
                await self._ws_manager.broadcast("system", {
                    "success": True, "message": "游戏已被取消",
                })
            raise
        except Exception as exc:
            self._status = GameStatus.IDLE
            self._error = str(exc)
            traceback.print_exc()
            if self._ws_manager:
                await self._ws_manager.broadcast("system", {
                    "success": False, "message": f"游戏异常终止: {exc}",
                })

    async def _event_callback(self, event_type: str, data: dict):
        """GameController._emit 的回调 —— 推送到 WebSocket。"""
        if not self._ws_manager:
            return

        state = self._controller.state if self._controller else None
        snapshot = serialize_game_state(state, "spectator") if state else None

        await self._ws_manager.broadcast_with_state(event_type, data, snapshot)

    def _broadcast_game_over(self):
        """游戏结束时的收尾广播。需要同步调度因为 _wrap_run 已在 async 上下文中。"""
        if not self._ws_manager:
            return

        state = self._controller.state if self._controller else None
        winner = state.winner.value if state and state.winner else "unknown"
        snapshot = serialize_game_state(state, "spectator") if state else None

        async def _broadcast():
            await self._ws_manager.broadcast_with_state(
                "game_over",
                {"winner": winner},
                snapshot,
            )

        asyncio.create_task(_broadcast())


def _get_phase_label(phase) -> str:
    """阶段枚举 → 中文标签。"""
    if phase is None:
        return ""
    from .serializer import get_phase_name
    return get_phase_name(phase)
