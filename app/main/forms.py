from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, SubmitField, FieldList, FormField, Form, BooleanField
from wtforms.validators import ValidationError, DataRequired, Length, Regexp
from sqlalchemy import select
from flask_babel import _, lazy_gettext as _l
from app import db
from app.models import Project

class EnvVarForm(Form):
    key = StringField(_l('Name'), validators=[
        DataRequired(),
        Length(min=1, max=100),
        Regexp(
            r'^[A-Za-z_][A-Za-z0-9_]*$',
            message=_("Keys can only contain letters, numbers and underscores. They can not start with a number.")
        )
    ])
    value = StringField(_l('Value'), validators=[DataRequired(), Length(min=1, max=1000)])
    

class ProjectForm(FlaskForm):
    name = StringField(_l('Project name'), validators=[
        DataRequired(),
        Length(min=1, max=100),
        Regexp(
            r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$',
            message=_('Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen.')
        )
    ])
    repo_id = IntegerField(_l('Repo ID'), validators=[DataRequired()])
    repo_branch = SelectField(_l('Branch'), choices=[], validators=[DataRequired(), Length(min=1, max=255)])
    framework = SelectField(_l('Framework presets'), choices=[('flask', 'Flask'), ('django', 'Django'), ('fastapi', 'FastAPI'), ('python', 'Python')], validators=[DataRequired(), Length(min=1, max=255)])
    root_directory = StringField(_l('Root directory'), validators=[
        Length(max=255, message=_('Root directory cannot exceed 255 characters')),
        Regexp(
            r'^[a-zA-Z0-9_\-./]*$',
            message=_('Root directory can only contain letters, numbers, dots, hyphens, underscores, and forward slashes')
        )
    ])
    use_custom_build_command = BooleanField(_l('Custom build command'), default=False)
    use_custom_pre_deploy_command = BooleanField(_l('Custom pre-deploy command'), default=False)
    use_custom_start_command = BooleanField(_l('Custom start command'), default=False)
    build_command = StringField(_l('Build command'))
    pre_deploy_command = StringField(_l('Pre-deploy command'))
    start_command = StringField(_l('Start command'))
    env_vars = FieldList(FormField(EnvVarForm))
    submit = SubmitField(_l('Save'))

    def validate_name(self, field):
        project = db.session.scalar(
            select(Project).where(Project.name == field.data)
        )
        if project is not None:
            raise ValidationError(_('A project with this name already exists.'))

    def validate_root_directory(self, field):
        if field.data:
            # Normalize the path
            path = field.data.strip().strip('/')

            if '..' in path or '/./' in path or '/../' in path:
                raise ValidationError(_('Invalid path: must be a valid subdirectory relative to repository root'))
            
            if '//' in path:
                raise ValidationError(_('Invalid path: cannot contain consecutive slashes'))
            
            # Store the normalized path
            field.data = path

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        
        if formdata:
            # Clean empty env_vars entries before validation runs
            self.env_vars.entries = [
                entry for entry in self.env_vars.entries
                if entry.data.get('key', '').strip() or entry.data.get('value', '').strip()
            ]
            
            # Set command fields to None if custom command is not enabled
            if not self.use_custom_build_command.data:
                self.build_command.data = None
            if not self.use_custom_pre_deploy_command.data:
                self.pre_deploy_command.data = None
            if not self.use_custom_start_command.data:
                self.start_command.data = None

class DeploymentForm(FlaskForm):
    submit = SubmitField(_l('Deploy'))