from starlette_wtf import StarletteForm
from wtforms import (
    StringField,
    SubmitField,
    BooleanField,
    FileField,
    HiddenField,
)
from wtforms.validators import ValidationError, DataRequired, Length, Regexp

from dependencies import get_translation as _


class NewTeamForm(StarletteForm):
    name = StringField(_("Name"), validators=[DataRequired(), Length(min=1, max=100)])
    submit = SubmitField(_("Create team"))


class TeamGeneralForm(StarletteForm):
    name = StringField(_("Display name"), validators=[DataRequired(), Length(min=1, max=100)])
    slug = StringField(
        _("Handle"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_(
                    "Team names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    avatar = FileField(_("Avatar"))
    delete_avatar = BooleanField(_("Delete avatar"), default=False)
    
    def validate_avatar(self, field):
        if field.data:
            if field.data.content_type not in [
                "image/jpeg",
                "image/png",
                "image/gif",
                "image/webp",
            ]:
                raise ValidationError(
                    _(
                        "Invalid file type. Only JPEG, PNG, GIF and WebP images are allowed."
                    )
                )
            if field.data.size > 10 * 1024 * 1024:  # 10MB
                raise ValidationError(
                    _("File size exceeds the maximum allowed (10MB).")
                )


class TeamDeleteForm(StarletteForm):
    name = HiddenField(_("Team Name"), validators=[DataRequired()])
    confirm = StringField(_("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_("Delete"), name="delete_team")

    def validate_confirm(self, field):
        if field.data != self.name.data: # type: ignore
            raise ValidationError(_("Team name confirmation did not match."))