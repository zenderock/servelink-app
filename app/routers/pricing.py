from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from dependencies import templates, TemplateResponse

router = APIRouter()


@router.get("/pricing", name="pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    """Display the pricing page."""
    return HTMLResponse("<h1>Pricing Page Test</h1><p>This is a test page.</p>")
