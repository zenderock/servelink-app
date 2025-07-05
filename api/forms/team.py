from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField, FileField, HiddenField, SubmitField
from flask_wtf.file import FileAllowed
from wtforms.validators import DataRequired, Length, Regexp, ValidationError
from flask_babel import _, lazy_gettext as _l


class TeamGeneralForm(FlaskForm):
    name = StringField(_l('Team name'), validators=[
        DataRequired(),
        Length(min=1, max=100),
        Regexp(
            r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$',
            message=_('Team names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen.')
        )
    ])
    slug = StringField(_l('Slug'), validators=[
        DataRequired(),
        Length(min=1, max=100),
        Regexp(
            r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$',
            message=_('Slugs can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen.')
        )
    ])
    avatar = FileField(_l('Avatar'), validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], _l('Images only (jpg, jpeg, png, gif, webp)'))])
    delete_avatar = BooleanField(_l('Delete avatar'), default=False)


class TeamDeleteForm(FlaskForm):
    name = HiddenField(_l('Name'), validators=[DataRequired()])
    confirm = StringField(_l('Confirmation'), validators=[DataRequired()])
    submit = SubmitField(_l('Delete'), name='delete_team')

    def validate_confirm(self, field):
        if field.data != self.name.data:
            raise ValidationError(_('Team name confirmation did not match.'))