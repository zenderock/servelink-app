from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from dependencies import templates

router = APIRouter()


@router.get("/pricing", name="pricing", response_class=HTMLResponse)
async def pricing(request: Request):
    """Display the pricing page."""
    return templates.TemplateResponse(
        request=request,
        name="pricing/pages/index.html",
        context={}
    )
