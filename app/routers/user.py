import logging
import os
from fastapi import APIRouter, Request, Depends, Query
from starlette.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
from authlib.jose import jwt
from datetime import timedelta
import resend

from config import Settings, get_settings
from dependencies import (
    get_translation as _,
    flash,
    TemplateResponse,
    templates,
    get_current_user,
    get_deployment_queue,
)
from db import get_db
from models import User, utc_now
from forms.user import UserDeleteForm, UserGeneralForm, UserEmailForm

logger = logging.getLogger(__name__)

router = APIRouter()


@router.api_route("/settings", methods=["GET", "POST"], name="user_settings")
async def user_settings(
    request: Request,
    fragment: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # Delete
    delete_form: Any = await UserDeleteForm.from_formdata(request, user=current_user)
    if request.method == "POST" and fragment == "danger":
        if await delete_form.validate_on_submit():
            try:
                delete_form.status = "deleted"
                await db.commit()

                # User is marked as deleted, actual cleanup is delegated to a job
                deployment_queue = await get_deployment_queue()
                await deployment_queue.enqueue_job(
                    "cleanup", current_user.id, job_timeout=300
                )

                flash(
                    request,
                    _('User "%(name)s" has been marked for deletion.')
                    % {"name": current_user.name},
                    "success",
                )
                return RedirectResponse("/")
            except Exception as e:
                await db.rollback()
                logger.error(
                    f'Error marking user "{current_user.username}" as deleted: {str(e)}'
                )
                flash(
                    request,
                    _("An error occurred while marking the user for deletion."),
                    "error",
                )

        for error in delete_form.confirm.errors:
            flash(request, error, "error")

        return RedirectResponse(
            url=str(request.url_for("user_settings")) + "#danger",
            status_code=303,
        )

    # General
    general_form: Any = await UserGeneralForm.from_formdata(
        request,
        data={"name": current_user.name, "username": current_user.username},
    )

    if fragment == "general":
        if request.method == "POST" and await general_form.validate_on_submit():
            # Name
            current_user.name = general_form.name.data or ""

            # Username
            old_username = current_user.username
            current_user.username = general_form.username.data or ""

            # Avatar upload
            avatar_file = general_form.avatar.data
            if (
                avatar_file
                and hasattr(avatar_file, "filename")
                and avatar_file.filename
            ):
                try:
                    from PIL import Image

                    avatar_dir = os.path.join(settings.upload_dir, "avatars")
                    os.makedirs(avatar_dir, exist_ok=True)

                    target_filename = f"user_{current_user.id}.webp"
                    target_filepath = os.path.join(avatar_dir, target_filename)

                    await avatar_file.seek(0)
                    img = Image.open(avatar_file.file)

                    if img.mode != "RGBA":
                        img = img.convert("RGBA")

                    max_size = (512, 512)
                    img.thumbnail(max_size)

                    img.save(target_filepath, "WEBP", quality=85)

                    current_user.has_avatar = True
                    current_user.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error processing avatar: {str(e)}")
                    flash(request, _("Avatar could not be updated."), "error")

            # Avatar deletion
            if general_form.delete_avatar.data:
                try:
                    avatar_dir = os.path.join(settings.upload_dir, "avatars")
                    filename = f"user_{current_user.id}.webp"
                    filepath = os.path.join(avatar_dir, filename)

                    if os.path.exists(filepath):
                        os.remove(filepath)

                    current_user.has_avatar = False
                    current_user.updated_at = utc_now()
                except Exception as e:
                    logger.error(f"Error deleting avatar: {str(e)}")
                    flash(request, _("Avatar could not be removed."), "error")

            await db.commit()
            flash(request, _("General settings updated."), "success")

            # Redirect if the name has changed
            if old_username != current_user.username:
                new_url = request.url_for("user_settings")

                if request.headers.get("HX-Request"):
                    return Response(
                        status_code=200, headers={"HX-Redirect": str(new_url)}
                    )
                else:
                    return RedirectResponse(new_url, status_code=303)

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="user/partials/_settings-general.html",
                context={
                    "current_user": current_user,
                    "general_form": general_form,
                },
            )

    # Email
    email_form: Any = await UserEmailForm.from_formdata(
        request, data={"email": current_user.email}
    )

    if fragment == "email":
        if request.method == "POST" and await email_form.validate_on_submit():
            new_email = email_form.email.data
            expires_at = utc_now() + timedelta(minutes=15)
            token_payload = {
                "user_id": current_user.id,
                "new_email": new_email,
                "exp": int(expires_at.timestamp()),
                "type": "email_change",
            }

            change_token = jwt.encode(
                {"alg": "HS256"}, token_payload, settings.secret_key
            )
            change_token_str = (
                change_token.decode("utf-8")
                if isinstance(change_token, bytes)
                else change_token
            )

            verify_link = str(
                request.url_for("auth_email_verify").include_query_params(
                    token=change_token_str
                )
            )

            resend.api_key = settings.resend_api_key

            try:
                resend.Emails.send(
                    {
                        "from": f"{settings.email_sender_name} <{settings.email_sender_address}>",
                        "to": [new_email],
                        "subject": _("Verify your new email address"),
                        "html": templates.get_template("email/change.html").render(
                            {
                                "request": request,
                                "email": new_email,
                                "verify_link": verify_link,
                                "email_logo": f"{settings.email_logo}"
                                or request.url_for("static", path="logo-email.png"),
                                "app_name": settings.app_name,
                                "app_description": settings.app_description,
                                "app_url": f"{settings.url_scheme}://app.{settings.base_domain}",
                            }
                        ),
                    }
                )
                flash(
                    request,
                    _(
                        "Verification email sent to %(email)s. Please check your inbox.",
                        email=new_email,
                    ),
                    "success",
                )
            except Exception as e:
                logger.error(f"Failed to send email change verification: {str(e)}")
                flash(
                    request,
                    _(
                        "Uh oh, something went wrong. We couldn't send a verification link to %(email)s. Please try again.",
                        email=new_email,
                    ),
                    "error",
                )

        if request.headers.get("HX-Request"):
            return TemplateResponse(
                request=request,
                name="user/partials/_settings-email.html",
                context={
                    "current_user": current_user,
                    "email_form": email_form,
                },
            )

    return TemplateResponse(
        request=request,
        name="user/pages/settings.html",
        context={
            "current_user": current_user,
            "delete_form": delete_form,
            "general_form": general_form,
            "email_form": email_form,
        },
    )
