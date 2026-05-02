from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from app.api.deps import get_agent_manager, get_repo
from app.models.job import AgentResponse
from app.repositories.job_repository import JobRepository
from app.services.agent_connection_manager import AgentConnectionManager


router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentResponse])
async def list_agents(repo: JobRepository = Depends(get_repo)) -> list[dict]:
    return await repo.list_agents()


@router.websocket("/{agent_id}/ws")
async def agent_websocket(
    websocket: WebSocket,
    agent_id: str,
    repo: JobRepository = Depends(get_repo),
    manager: AgentConnectionManager = Depends(get_agent_manager),
) -> None:
    await manager.connect(agent_id, websocket)
    await repo.heartbeat_agent(agent_id, is_online=True)
    await websocket.send_json({"type": "hello", "agent_id": agent_id})
    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "heartbeat":
                agent = await repo.heartbeat_agent(
                    agent_id,
                    printer_name=message.get("printer_name"),
                    printer_status=message.get("printer_status", "UNKNOWN"),
                    details=message.get("details") or {},
                    is_online=True,
                )
                await websocket.send_json({"type": "heartbeat_ack", "agent": agent})

            elif message_type == "claim_next":
                job = await repo.claim_next_for_agent(agent_id)
                if job is None:
                    await websocket.send_json({"type": "no_job"})
                else:
                    await websocket.send_json({"type": "job", "job": job})

            elif message_type == "job_status":
                job = await repo.update_agent_job_status(
                    agent_id,
                    int(message["job_id"]),
                    str(message["status"]),
                    error_message=message.get("error_message"),
                    file_size_bytes=message.get("file_size_bytes"),
                    retryable=bool(message.get("retryable", True)),
                )
                await websocket.send_json({"type": "job_status_ack", "job": job})

            elif message_type == "local_cleanup_done":
                await websocket.send_json(
                    {"type": "local_cleanup_ack", "deleted": int(message.get("deleted") or 0)}
                )

            else:
                await websocket.send_json({"type": "error", "detail": f"Unknown message type: {message_type}"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(agent_id, websocket)
        await repo.mark_agent_offline(agent_id)
