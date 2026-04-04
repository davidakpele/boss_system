# src/services/websocket_manager.py
from fastapi import WebSocket
from typing import Dict, List, Set
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # channel_id -> list of {ws, user_id, user_name}
        self.channel_connections: Dict[int, List[dict]] = {}
        # user_id -> list of WebSockets (multiple tabs/channels)
        self.user_connections: Dict[int, List[WebSocket]] = {}

    async def connect_to_channel(self, websocket: WebSocket, channel_id: int, user_id: int, user_name: str):
        await websocket.accept()

        if channel_id not in self.channel_connections:
            self.channel_connections[channel_id] = []
        self.channel_connections[channel_id].append({
            "ws": websocket,
            "user_id": user_id,
            "user_name": user_name,
        })

        # Support multiple connections per user (multiple tabs)
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(websocket)

        logger.info(f"User {user_name} ({user_id}) connected to channel {channel_id}")

    def disconnect_from_channel(self, websocket: WebSocket, channel_id: int, user_id: int):
        if channel_id in self.channel_connections:
            self.channel_connections[channel_id] = [
                c for c in self.channel_connections[channel_id]
                if c["ws"] != websocket
            ]

        # Only remove this specific websocket from user connections
        if user_id in self.user_connections:
            self.user_connections[user_id] = [
                ws for ws in self.user_connections[user_id]
                if ws != websocket
            ]
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]

    async def broadcast_to_channel(self, channel_id: int, message: dict, exclude_user: int = None):
        if channel_id not in self.channel_connections:
            return
        dead = []
        for conn in self.channel_connections[channel_id]:
            if exclude_user and conn["user_id"] == exclude_user:
                continue
            try:
                await conn["ws"].send_json(message)
            except Exception:
                dead.append(conn)
        for d in dead:
            try:
                self.channel_connections[channel_id].remove(d)
            except ValueError:
                pass

    async def send_to_user(self, user_id: int, message: dict):
        """Send to ALL active connections for a user (multiple tabs)."""
        sockets = self.user_connections.get(user_id, [])
        dead = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self.user_connections[user_id].remove(ws)
            except (ValueError, KeyError):
                pass

    def get_online_users_in_channel(self, channel_id: int) -> List[int]:
        if channel_id not in self.channel_connections:
            return []
        return [c["user_id"] for c in self.channel_connections[channel_id]]

    def get_all_online_user_ids(self) -> Set[int]:
        return set(self.user_connections.keys())

    def is_user_online(self, user_id: int) -> bool:
        return user_id in self.user_connections and len(self.user_connections[user_id]) > 0


manager = ConnectionManager()