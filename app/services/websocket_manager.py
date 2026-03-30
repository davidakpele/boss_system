from fastapi import WebSocket
from typing import Dict, List, Set
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.channel_connections: Dict[int, List[dict]] = {}
        self.user_connections: Dict[int, WebSocket] = {}

    async def connect_to_channel(self, websocket: WebSocket, channel_id: int, user_id: int, user_name: str):
        await websocket.accept()
        if channel_id not in self.channel_connections:
            self.channel_connections[channel_id] = []
        self.channel_connections[channel_id].append({
            "ws": websocket,
            "user_id": user_id,
            "user_name": user_name,
        })
        self.user_connections[user_id] = websocket
        logger.info(f"User {user_name} connected to channel {channel_id}")

    def disconnect_from_channel(self, websocket: WebSocket, channel_id: int, user_id: int):
        if channel_id in self.channel_connections:
            self.channel_connections[channel_id] = [
                c for c in self.channel_connections[channel_id]
                if c["ws"] != websocket
            ]
        if user_id in self.user_connections:
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
        # Cleanup dead connections
        for d in dead:
            self.channel_connections[channel_id].remove(d)

    async def send_to_user(self, user_id: int, message: dict):
        ws = self.user_connections.get(user_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                del self.user_connections[user_id]

    def get_online_users_in_channel(self, channel_id: int) -> List[int]:
        if channel_id not in self.channel_connections:
            return []
        return [c["user_id"] for c in self.channel_connections[channel_id]]

    def get_all_online_user_ids(self) -> Set[int]:
        return set(self.user_connections.keys())


manager = ConnectionManager()
