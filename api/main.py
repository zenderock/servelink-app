from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import asyncio
import redis.asyncio as redis
import os
import time
from utils.token import verify_token
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from routers import auth, team, github
from dependencies import templates
from config import get_settings
from db import get_db

app = FastAPI()

# Add session middleware for flash messages
settings = get_settings()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth.router)
app.include_router(team.router)
app.include_router(github.router)

# Add this after including routers
print("Registered routes:")
for route in app.routes:
    if hasattr(route, 'methods'):
        print(f"{route.methods} {route.path}")

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_client = redis.from_url(redis_url, decode_responses=True)

@app.get("/events/deployments/{token}")
async def stream_deployment_events(
    token: str,
    request: Request
):
    payload = verify_token(token, os.getenv('SECRET_KEY'))
    project_id = payload.get('pid')
    deployment_id = payload.get('did')
    
    async def event_generator():
        status_stream = f"stream:project:{project_id}:deployment:{deployment_id}:status"
        logs_stream = f"stream:project:{project_id}:deployment:{deployment_id}:logs"
        
        last_event_id = request.headers.get("Last-Event-ID") # Reconnection
        
        streams = {
            logs_stream: last_event_id if last_event_id else "0-0",
            status_stream: last_event_id if last_event_id else "$"
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
                            if message_fields.get('deployment_status') in ["succeeded", "failed"]:
                                deployment_conclusion = message_fields.get('deployment_status')
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
                            logs_html = templates.get_template("deployment/components/logs.html").module.logs(logs_list)
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


@app.get("/events/projects/{token}")
async def stream_project_events(
    token: str,
    request: Request
):
    payload = verify_token(token, os.getenv('SECRET_KEY'))
    project_id = payload.get('pid')
    token_exp_time = payload.get('exp')
    
    async def event_generator():
        status_stream = f"stream:project:{project_id}:updates"
        
        last_event_id = request.headers.get("Last-Event-ID") # Reconnection
        start_position = last_event_id if last_event_id else f"{int(time.time() * 1000) - 2000}-0"
        print(f"start_position: {start_position}")
        
        streams = { status_stream: start_position }
        
        
        try:
            while True:
                if time.time() > token_exp_time:
                    yield "event: session_expired\n"
                    yield "data: Your session has expired. Please reconnect.\n\n"
                    break

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
                            status_html = templates.get_template("deployment/components/options.html").module.status(
                                conclusion=message_fields.get("deployment_status"),
                                compact=True,
                                tooltip=True,
                                attrs={
                                    'data-deployment-status': message_fields.get('deployment_id'),
                                    'hx-swap-oob': f"outerHTML:[data-deployment-status='{message_fields.get('deployment_id')}']"
                                }
                            )
                            status_html = status_html.replace('\n', '').replace('\r', '')

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
        }
    )


@app.get("/db-test")
async def db_test(db: AsyncSession = Depends(get_db)):
    """Simple endpoint to check Postgres connectivity using SQLAlchemy."""
    try:
        result = await db.execute(text("SELECT 1"))
        value = result.scalar()
        return {"db_alive": value == 1}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
