# src/services/websocket_manager.py
"""
WebSocket connection manager.
Supports:
  - channel-based broadcast (messages, typing, reactions)
  - user-targeted send (mentions, call signaling, notifications)
"""
import json
import logging
from fastapi import WebSocket
 
logger = logging.getLogger(__name__)
 
 
class WebSocketManager:
    def __init__(self):
        self.channel_connections: dict[int, set] = {}
        self.user_connections: dict[int, set] = {}
 
    async def connect_to_channel(
        self,
        websocket: WebSocket,
        channel_id: int,
        user_id: int,
        user_name: str,
    ):
        await websocket.accept()
 
        if channel_id not in self.channel_connections:
            self.channel_connections[channel_id] = set()
        self.channel_connections[channel_id].add((websocket, user_id, user_name))
 
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)
 
        logger.info(f"WS connected: user={user_id} channel={channel_id}")
 
    def disconnect_from_channel(
        self,
        websocket: WebSocket,
        channel_id: int,
        user_id: int,
    ):
        if channel_id in self.channel_connections:
            self.channel_connections[channel_id] = {
                t for t in self.channel_connections[channel_id]
                if t[0] is not websocket
            }
            if not self.channel_connections[channel_id]:
                del self.channel_connections[channel_id]
 
        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
 
        logger.info(f"WS disconnected: user={user_id} channel={channel_id}")
 
    async def broadcast_to_channel(
        self,
        channel_id: int,
        payload: dict,
        exclude_user: int | None = None,
    ):
        """Send payload to everyone in a channel."""
        if channel_id not in self.channel_connections:
            return
 
        dead = set()
        for entry in list(self.channel_connections[channel_id]):
            ws, uid, uname = entry
            if exclude_user is not None and uid == exclude_user:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(entry)
 
        if dead:
            self.channel_connections[channel_id] -= dead
 
    async def send_to_user(self, user_id: int, payload: dict) -> bool:
        """
        Send payload directly to a specific user.
        Used for: call signaling, @mention notifications, system alerts.
        Returns True if at least one connection received it.
        """
        if user_id not in self.user_connections:
            logger.debug(f"send_to_user: user {user_id} not connected")
            return False
 
        sent = False
        dead = set()
        for ws in list(self.user_connections[user_id]):
            try:
                await ws.send_json(payload)
                sent = True
            except Exception as e:
                logger.warning(f"send_to_user failed ws for user {user_id}: {e}")
                dead.add(ws)
 
        if dead:
            self.user_connections[user_id] -= dead
 
        return sent
 
    def get_online_users(self, channel_id: int) -> list[int]:
        """Return list of user IDs currently connected to a channel."""
        if channel_id not in self.channel_connections:
            return []
        return list({uid for _, uid, _ in self.channel_connections[channel_id]})
 
    def get_all_online_user_ids(self) -> list[int]:
        """Return deduplicated list of all currently connected user IDs."""
        return list(self.user_connections.keys())

    def is_user_online(self, user_id: int) -> bool:
        return user_id in self.user_connections and bool(self.user_connections[user_id])
 
    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self.channel_connections.values())
 
 
manager = WebSocketManager()