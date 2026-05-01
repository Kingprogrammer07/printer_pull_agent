from collections import defaultdict

from fastapi import WebSocket


class AgentConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, agent_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[agent_id].add(websocket)

    def disconnect(self, agent_id: str, websocket: WebSocket) -> None:
        self._connections[agent_id].discard(websocket)
        if not self._connections[agent_id]:
            self._connections.pop(agent_id, None)

    async def send(self, agent_id: str, message: dict) -> None:
        dead: list[WebSocket] = []
        for websocket in self._connections.get(agent_id, set()):
            try:
                await websocket.send_json(message)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(agent_id, websocket)

    async def broadcast(self, message: dict) -> None:
        for agent_id in list(self._connections):
            await self.send(agent_id, message)

    def connected_count(self) -> int:
        return sum(len(items) for items in self._connections.values())

    def connected_agents(self) -> list[str]:
        return sorted(self._connections)
