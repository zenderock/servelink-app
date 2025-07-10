from starlette_wtf import StarletteForm
from wtforms import (
    StringField,
    SubmitField,
    BooleanField,
    FileField,
    HiddenField,
)
from wtforms.validators import ValidationError, DataRequired, Length, Regexp

from dependencies import get_translation as _, get_lazy_translation as _l


class NewTeamForm(StarletteForm):
    name = StringField(_l("Name"), validators=[DataRequired(), Length(min=1, max=100)])
    submit = SubmitField(_l("Create team"))


class TeamGeneralForm(StarletteForm):
    name = StringField(
        _l("Display name"), validators=[DataRequired(), Length(min=1, max=100)]
    )
    slug = StringField(
        _l("Handle"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_l(
                    "Team names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    avatar = FileField(_l("Avatar"))
    delete_avatar = BooleanField(_l("Delete avatar"), default=False)

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
    name = HiddenField(_l("Team Name"), validators=[DataRequired()])
    confirm = StringField(_l("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_l("Delete"), name="delete_team")

    def validate_confirm(self, field):
        if field.data != self.name.data:  # type: ignore
            raise ValidationError(_("Team name confirmation did not match."))
