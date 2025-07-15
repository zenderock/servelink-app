import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
import asyncio
import time
from typing import Any

from config import get_settings, Settings
from models import Team, Project, Deployment
from dependencies import (
    get_deployment_by_id,
    get_project_by_id,
    get_redis_client,
    get_team_by_slug,
    templates,
    get_db,
)

router = APIRouter()

logger = logging.getLogger(__name__)


STREAM_TTL = 900


@router.get(
    "/api/{team_slug}/deployments/{deployment_id}/events", name="api_deployment_events"
)
async def api_deployment_events(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    team: Team = Depends(get_team_by_slug),
    deployment: Deployment = Depends(get_deployment_by_id),
    redis_client: Redis = Depends(get_redis_client),
):
    async def event_generator():
        status_stream = (
            f"stream:project:{deployment.project_id}:deployment:{deployment.id}:status"
        )
        logs_stream = (
            f"stream:project:{deployment.project_id}:deployment:{deployment.id}:logs"
        )

        last_event_id = request.headers.get("Last-Event-ID")  # Reconnection

        streams: Any = {
            logs_stream: last_event_id if last_event_id else "0-0",
            status_stream: last_event_id if last_event_id else "$",
        }

        logs_template = templates.get_template("deployment/macros/logs.html")

        try:
            # start_ts   = time.time()
            while True:
                # TODO: Add stream expiration
                # if time.time() - start_ts > STREAM_TTL:
                #     yield "event: stream_expired\n"
                #     yield "data: The stream has expired. Please reconnect.\n\n"
                #     break

                deployment_conclusion = None
                messages = await redis_client.xread(streams, block=5000)

                if not messages:
                    await asyncio.sleep(1)
                    continue

                for stream_name, stream_messages in messages:
                    if stream_name == status_stream:
                        for message_id, message_fields in stream_messages:
                            if message_fields.get("deployment_status") in [
                                "succeeded",
                                "failed",
                            ]:
                                deployment_conclusion = message_fields.get(
                                    "deployment_status"
                                )
                            streams[stream_name] = message_id

                    else:
                        logs_list = []
                        last_message_id = None
                        for message_id, message_fields in stream_messages:
                            logs_list.append(
                                {
                                    "timestamp": message_fields.get("timestamp", ""),
                                    "message": message_fields.get("message", ""),
                                }
                            )
                            last_message_id = message_id
                            streams[stream_name] = message_id

                        if logs_list:
                            logs_html = logs_template.module.logs(logs_list)
                            logs_html = logs_html.replace("\n", "").replace("\r", "")

                            yield f"id: {last_message_id}\n"
                            yield "event: deployment_log\n"
                            yield f"data: {logs_html}\n\n"

                if deployment_conclusion:
                    yield "event: deployment_concluded\n"
                    yield f"data: {deployment_conclusion}\n\n"
                    break

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


@router.get("/api/{team_slug}/projects/{project_id}/events", name="api_project_events")
async def api_project_events(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    team: Team = Depends(get_team_by_slug),
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
            # start_ts   = time.time()
            while True:
                # if time.time() - start_ts > STREAM_TTL:
                #     yield "event: stream_expired\n"
                #     yield "data: The stream has expired. Please reconnect.\n\n"
                #     break

                messages = await redis_client.xread(streams, block=5000)

                if not messages:
                    await asyncio.sleep(1)
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, message_fields in stream_messages:
                        yield f"id: {message_id}\n"
                        yield f"event: {message_fields.get('event_type')}\n"
                        if message_fields.get("event_type") == "deployment_created":
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
