import logging
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
import asyncio
import time
from typing import Any

from models import Team, Project, Deployment, User, utc_now
from dependencies import (
    get_current_user,
    get_deployment_by_id,
    get_project_by_id,
    get_redis_client,
    get_team_by_id,
    templates,
)

router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)

STREAM_TTL = 900


@router.get(
    "/{team_id}/projects/{project_id}/deployments/{deployment_id}/events",
    name="api_deployment_events",
)
async def api_deployment_events(
    request: Request,
    start_timestamp: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    team: Team = Depends(get_team_by_id),
    project: Project = Depends(get_project_by_id),
    deployment: Deployment = Depends(get_deployment_by_id),
    redis_client: Redis = Depends(get_redis_client),
):
    async def event_generator():
        status_stream = (
            f"stream:project:{deployment.project_id}:deployment:{deployment.id}:status"
        )
        status_start_position = "0-0"

        last_event_id = request.headers.get("Last-Event-ID")  # Reconnection
        logs_start_timestamp = (
            int(last_event_id)
            if last_event_id
            else start_timestamp
            if start_timestamp
            else None
        )

        logs_template = templates.get_template("deployment/macros/log-list.html")

        deployment_conclusion = None

        try:
            while True:
                logs = await request.app.state.loki_service.get_logs(
                    project_id=deployment.project_id,
                    deployment_id=deployment.id,
                    start_timestamp=logs_start_timestamp,
                    limit=5000,
                )

                if logs:
                    logs_html = logs_template.module.log_list(logs=logs)
                    yield "event: deployment_log\n"
                    yield f"data: {logs_html.replace(chr(10), '').replace(chr(13), '')}\n\n"
                    logs_start_timestamp = (
                        max(int(log["timestamp"]) for log in logs) + 1
                    )

                if not (
                    deployment.status != "completed"
                    or deployment.container_status == "running"
                    or (
                        deployment.concluded_at
                        and (utc_now() - deployment.concluded_at).total_seconds() < 5
                    )
                ):
                    yield "event: deployment_log_closed\n"
                    yield f"data: {deployment_conclusion}\n\n"

                if not deployment_conclusion:
                    try:
                        messages = await asyncio.wait_for(
                            redis_client.xread(
                                {status_stream: status_start_position}, block=100
                            ),
                            timeout=0.1,
                        )
                        for stream_name, stream_messages in messages:
                            for message_id, message_fields in stream_messages:
                                if message_fields.get("deployment_status") in [
                                    "succeeded",
                                    "failed",
                                ]:
                                    deployment_conclusion = message_fields.get(
                                        "deployment_status"
                                    )
                                    yield "event: deployment_concluded\n"
                                    yield f"data: {deployment_conclusion}\n\n"
                                status_start_position = message_id
                    except asyncio.TimeoutError:
                        pass

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/{team_id}/projects/{project_id}/events", name="api_project_events")
async def api_project_events(
    request: Request,
    current_user: User = Depends(get_current_user),
    team: Team = Depends(get_team_by_id),
    project: Project = Depends(get_project_by_id),
    redis_client: Redis = Depends(get_redis_client),
):
    async def event_generator():
        status_stream = f"stream:project:{project.id}:updates"

        last_event_id = request.headers.get("Last-Event-ID")  # Reconnection
        start_position = (
            last_event_id if last_event_id else f"{int(time.time() * 1000) - 2000}-0"
        )

        streams: Any = {status_stream: start_position}

        status_template = templates.get_template("deployment/macros/status.html")

        try:
            start_ts = time.time()
            while True:
                if time.time() - start_ts > STREAM_TTL:
                    yield "event: stream_expired\n"
                    yield "data: The stream has expired. Please reconnect.\n\n"
                    break

                messages = await redis_client.xread(streams, block=5000)

                if not messages:
                    await asyncio.sleep(1)
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, message_fields in stream_messages:
                        yield f"id: {message_id}\n"
                        yield f"event: {message_fields.get('event_type')}\n"
                        if message_fields.get("event_type") == "deployment_creation":
                            yield f"data: {message_fields.get('deployment_id')}\n\n"
                        else:
                            status_html = status_template.module.status(
                                conclusion=message_fields.get("deployment_status"),
                                compact=True,
                                tooltip=True,
                                attrs={
                                    "data-deployment-status": message_fields.get(
                                        "deployment_id"
                                    ),
                                    "hx-swap-oob": f"outerHTML:[data-deployment-status='{message_fields.get('deployment_id')}']",
                                },
                            )
                            status_html = status_html.replace("\n", "").replace(
                                "\r", ""
                            )

                            yield f"data: {status_html.strip()}\n\n"

                        streams[stream_name] = message_id

        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
