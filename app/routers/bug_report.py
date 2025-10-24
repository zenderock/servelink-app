import logging
import base64
from fastapi import APIRouter, Request, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from config import Settings, get_settings
from dependencies import get_current_user, templates
from db import get_db
from models import User
from services.onesignal import OneSignalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bug-report")


@router.post("/submit", name="submit_bug_report")
async def submit_bug_report(
    request: Request,
    title: str = Form(..., max_length=200),
    description: str = Form(..., max_length=2000),
    attachment: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        max_file_size = 10 * 1024 * 1024
        attachment_info = None
        
        if attachment and attachment.filename:
            content = await attachment.read()
            if len(content) > max_file_size:
                return JSONResponse(
                    status_code=400,
                    content={"error": "File size must be less than 10MB"}
                )
            
            attachment_info = {
                "filename": attachment.filename,
                "size": len(content),
                "content_type": attachment.content_type
            }
        
        html_content = templates.get_template("email/bug-report.html").render({
            "request": request,
            "title": title,
            "description": description,
            "user_name": current_user.name or current_user.username,
            "user_email": current_user.email,
            "attachment_info": attachment_info,
            "app_name": settings.app_name,
            "app_url": f"{settings.url_scheme}://{settings.app_hostname}",
        })
        
        async with OneSignalService(settings) as onesignal:
            recipients = ["support@servel.ink", "aubigo.techs@gmail.com"]
            
            for recipient in recipients:
                await onesignal.send_email(
                    to_email=recipient,
                    subject=f"🐛 Bug Report: {title}",
                    html_content=html_content,
                    from_name=settings.email_sender_name,
                    from_address=settings.email_sender_address,
                    reply_to=current_user.email,
                    auto_register=False
                )
        
        logger.info(f"Bug report submitted by user {current_user.email}: {title}")
        
        return JSONResponse(
            status_code=200,
            content={"message": "Bug report submitted successfully"}
        )
        
    except Exception as e:
        logger.error(f"Error submitting bug report: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to submit bug report"}
        )
