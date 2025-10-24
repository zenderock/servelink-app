from fastapi import APIRouter, Request
from dependencies import templates, TemplateResponse

router = APIRouter()


@router.get("/pricing", name="pricing")
async def pricing(request: Request):
    """Display the pricing page."""
    return TemplateResponse(
        request=request,
        name="pricing/pages/index.html",
        context={}
    )
