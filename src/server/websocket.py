"""WebSocket 连接管理器：管理客户端连接、广播事件、接收命令。"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect


class WebSocketManager:
    """管理所有 WebSocket 连接，提供广播和单播能力。"""

    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._game_manager = None  # 由 app.py 注入

    def set_game_manager(self, game_manager) -> None:
        self._game_manager = game_manager

    # ============================================================
    # 连接管理
    # ============================================================

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    # ============================================================
    # 消息发送
    # ============================================================

    async def broadcast(self, event_type: str, data: dict) -> None:
        """向所有已连接客户端广播事件。"""
        message = {
            "type": "game_event",
            "event": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)

        for ws in stale:
            self._connections.discard(ws)

    async def broadcast_with_state(self, event_type: str, data: dict, state_snapshot: dict) -> None:
        """广播事件并附带当前游戏状态快照。"""
        message = {
            "type": "game_event",
            "event": event_type,
            "timestamp": time.time(),
            "data": data,
            "state_snapshot": state_snapshot,
        }
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)

        for ws in stale:
            self._connections.discard(ws)

    async def send_to(self, websocket: WebSocket, message: dict) -> None:
        """向单个客户端发送消息。"""
        try:
            await websocket.send_json(message)
        except Exception:
            self._connections.discard(websocket)

    # ============================================================
    # 客户端命令处理
    # ============================================================

    async def handle_client_message(self, websocket: WebSocket, raw: str) -> None:
        """解析客户端 JSON 命令并分发处理。"""
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            await self.send_to(websocket, {
                "type": "error",
                "message": "无效的 JSON 格式",
            })
            return

        msg_type = msg.get("type", "")

        if msg_type == "start_game":
            await self._handle_start_game(websocket, msg)
        elif msg_type == "stop_game":
            await self._handle_stop_game(websocket)
        elif msg_type == "request_state":
            await self._handle_request_state(websocket)
        else:
            await self.send_to(websocket, {
                "type": "error",
                "message": f"未知命令类型: {msg_type}",
            })

    async def _handle_start_game(self, websocket: WebSocket, msg: dict) -> None:
        gm = self._game_manager
        if not gm:
            await self.send_to(websocket, {"type": "error", "message": "GameManager 未初始化"})
            return

        mode = msg.get("mode", "auto")
        config = msg.get("config", None)

        result = await gm.start_game(mode, config)
        # start_game 返回结果也推送给所有客户端（as a system message）
        await self.broadcast("system", result)

    async def _handle_stop_game(self, websocket: WebSocket) -> None:
        gm = self._game_manager
        if not gm:
            await self.send_to(websocket, {"type": "error", "message": "GameManager 未初始化"})
            return

        result = await gm.stop_game()
        await self.broadcast("system", result)

    async def _handle_request_state(self, websocket: WebSocket) -> None:
        gm = self._game_manager
        if not gm:
            await self.send_to(websocket, {"type": "error", "message": "GameManager 未初始化"})
            return

        state = gm.get_serializable_state("spectator")
        status = gm.get_status()
        await self.send_to(websocket, {
            "type": "game_state",
            "status": status,
            "state": state,
        })
