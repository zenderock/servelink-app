from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import redis.asyncio as redis
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://app.localhost", "http://localhost:5000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_client = redis.from_url(redis_url, decode_responses=True)

templates = Jinja2Templates(directory="shared/templates")

@app.get("/projects/{project_id}/deployments/{deployment_id}/events")
async def stream_deployment_events(
    project_id: str, 
    deployment_id: str,
    request: Request
):
    async def event_generator():
        status_stream = f"stream:project:{project_id}:deployment:{deployment_id}:status"
        logs_stream = f"stream:project:{project_id}:deployment:{deployment_id}:logs"
        
        last_event_id = request.headers.get("Last-Event-ID") # Reconnection
        start_position = last_event_id if last_event_id else "$"
        
        streams = {
            logs_stream: start_position,
            status_stream: start_position
        }
        
        try:
            while True:
                deployment_conclusion = None
                messages = await redis_client.xread(streams, block=5000)
                
                if not messages:
                    await asyncio.sleep(1)
                    continue

                for stream_name, stream_messages in messages:
                    if stream_name == status_stream:
                        for message_id, message_fields in stream_messages:
                            if message_fields.get('status') in ["succeeded", "failed"]:
                                deployment_conclusion = message_fields.get('status')
                            streams[stream_name] = message_id
                    
                    else:
                        logs_list = []
                        last_message_id = None
                        for message_id, message_fields in stream_messages:
                            logs_list.append({
                                "timestamp": message_fields.get('timestamp', ''),
                                "message": message_fields.get('message', '')
                            })
                            last_message_id = message_id
                            streams[stream_name] = message_id

                        if logs_list:
                            logs_html = templates.get_template("components/logs.html").module.logs(logs_list)
                            logs_html = logs_html.replace('\n', '').replace('\r', '')

                            yield f"id: {last_message_id}\n"
                            yield f"event: deployment_log\n"
                            yield f"data: {logs_html}\n\n"
                
                if deployment_conclusion:
                    yield f"event: deployment_concluded\n"
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
        }
    )


@app.get("/projects/{project_id}/events")
async def stream_project_events(
    project_id: str, 
    request: Request
):
    async def event_generator():
        status_stream = f"stream:project:{project_id}:updates"
        
        last_event_id = request.headers.get("Last-Event-ID") # Reconnection
        start_position = last_event_id if last_event_id else "$"
        
        streams = { status_stream: start_position }
        
        try:
            while True:
                messages = await redis_client.xread(streams, block=5000)
                
                if not messages:
                    await asyncio.sleep(1)
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, message_fields in stream_messages:
                        yield f"id: {message_id}\n"
                        yield f"event: {message_fields.get('event_type')}\n"
                        if (message_fields.get('event_type') == 'deployment_created'):
                            yield f"data: {message_fields.get('deployment_id')}\n\n"
                        else:
                            yield f"data: {message_fields.get('deployment_id')}\n\n"
                
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
