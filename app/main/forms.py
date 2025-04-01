from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, SubmitField, FieldList, FormField, Form, BooleanField, FileField, HiddenField
from flask_wtf.file import FileAllowed
from wtforms.validators import ValidationError, DataRequired, Length, Regexp
from sqlalchemy import select
from flask_babel import _, lazy_gettext as _l
from app import db
from app.models import Project
from app.helpers.colors import COLORS
from app.helpers.environments import get_environment_for_branch
import re


def validate_root_directory(form, field):
    if field.data:
        # Normalize the path
        path = field.data.strip().strip('/')

        if '..' in path or '/./' in path or '/../' in path:
            raise ValidationError(_('Invalid path: must be a valid subdirectory relative to repository root'))
        
        if '//' in path:
            raise ValidationError(_('Invalid path: cannot contain consecutive slashes'))
        
        # Store the normalized path
        field.data = path


def process_env_vars(form, formdata):
    """Clean empty env_vars entries before validation runs"""
    if formdata and hasattr(form, 'env_vars'):
        form.env_vars.entries = [
            entry for entry in form.env_vars.entries
            if entry.data.get('key', '').strip() or entry.data.get('value', '').strip()
        ]


def process_commands_and_root_directory(form, formdata):
    """Set command fields to None if custom command is not enabled"""
    if formdata:
        if hasattr(form, 'use_custom_build_command') and not form.use_custom_build_command.data:
            form.build_command.data = None
        if hasattr(form, 'use_custom_pre_deploy_command') and not form.use_custom_pre_deploy_command.data:
            form.pre_deploy_command.data = None
        if hasattr(form, 'use_custom_start_command') and not form.use_custom_start_command.data:
            form.start_command.data = None
        if hasattr(form, 'use_custom_root_directory') and not form.use_custom_root_directory.data:
            form.root_directory.data = None


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
    environment = SelectField(_l('Environment'), default='')

    def __init__(self, *args, parent_entries=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_entries = parent_entries or []
        # Add a unique identifier to each form instance
        self._form_id = id(self)

    def validate_key(self, field):
        current_pair = (field.data.strip(), self.environment.data.strip())
        for entry in self.parent_entries:
            # Compare using the unique identifier
            if entry._form_id != self._form_id and (entry.key.data.strip(), entry.environment.data.strip()) == current_pair:
                raise ValidationError(_('Duplicate key "{}" for environment "{}"').format(
                    field.data, self.environment.data or _('All environments')
                ))


class EnvVarsForm(FlaskForm):
    env_vars = FieldList(FormField(EnvVarForm))

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_env_vars(self, formdata)
        for entry in self.env_vars.entries:
            entry.form.parent_entries = self.env_vars.entries


class ProdEnvironmentForm(FlaskForm):
    color = SelectField(_l('Color'), validators=[DataRequired()], choices=[(color, color) for color in COLORS])
    branch = SelectField(_l('Branch'), choices=[], validators=[DataRequired(), Length(min=1, max=255)])


class CustomEnvironmentForm(FlaskForm):
    environment_id = HiddenField()
    color = SelectField(_l('Color'), validators=[DataRequired()], choices=[(color, color) for color in COLORS])
    name = StringField(_l('Name'), validators=[DataRequired(), Length(min=1, max=255)])
    slug = StringField(_l('Identifier'), validators=[
        DataRequired(),
        Length(min=1, max=255),
        Regexp(
            r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$',
            message=_('Environment IDs can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen.')
        )
    ])
    branch = StringField(_l('Branch pattern'), validators=[DataRequired(), Length(min=1, max=255)])

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project 

    def validate_slug(self, field):
        if self.environment_id.data:
            env = self.project.get_environment_by_id(self.environment_id.data)
            if env and field.data == env['slug']:
                return
            
        if self.project.has_active_environment_with_slug(field.data):
            raise ValidationError(_('An environment with this identifier already exists.'))


class DeleteEnvironmentForm(FlaskForm):
    environment_id = HiddenField(validators=[DataRequired()])
    confirm = StringField(_l('Confirmation'), validators=[DataRequired()])
    submit = SubmitField(_l('Delete'))

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project 
    
    def validate_confirm(self, field):
        environment = self.project.get_environment_by_id(self.environment_id.data)
        if not environment:
            raise ValidationError(_('Environment not found.'))
        if field.data != environment['slug']:
            raise ValidationError(_('Environment identifier confirmation did not match.'))


class BuildAndDeployForm(FlaskForm):
    framework = SelectField(
        _l('Framework presets'),
        choices=[
            ('flask', 'Flask'),
            ('django', 'Django'),
            ('fastapi', 'FastAPI'),
            ('python', 'Python')
        ],
        validators=[DataRequired(), Length(min=1, max=255)]
    )
    runtime = SelectField(
        _l('Runtime'),
        choices=[
            ('python-3', 'Python 3'),
            ('python-2', 'Python 2'),
            ('pypy', 'PyPy')
        ],
        validators=[DataRequired(), Length(min=1, max=255)]
    )
    use_custom_root_directory = BooleanField(_l('Custom root directory'), default=False)
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

    validate_root_directory = validate_root_directory
    
    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_commands_and_root_directory(self, formdata)


class GeneralForm(FlaskForm):
    name = StringField(_l('Project name'), validators=[
        DataRequired(),
        Length(min=1, max=100),
        Regexp(
            r'^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$',
            message=_('Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen.')
        )
    ])
    avatar = FileField(_l('Avatar'), validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], _l('Images only (jpg, jpeg, png, gif, webp)'))])
    delete_avatar = BooleanField(_l('Delete avatar'), default=False)
    repo_id = IntegerField(_l('Repo ID'), validators=[DataRequired()])


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
    production_branch = SelectField(_l('Production branch'), choices=[], validators=[DataRequired(), Length(min=1, max=255)])
    framework = SelectField(
        _l('Framework presets'),
        choices=[
            ('flask', 'Flask'),
            ('django', 'Django'),
            ('fastapi', 'FastAPI'),
            ('python', 'Python')
        ],
        validators=[DataRequired(), Length(min=1, max=255)]
    )
    runtime = SelectField(
        _l('Runtime'),
        choices=[
            ('python-3', 'Python 3'),
            ('python-2', 'Python 2'),
            ('pypy', 'PyPy')
        ],
        validators=[DataRequired(), Length(min=1, max=255)]
    )
    use_custom_root_directory = BooleanField(_l('Custom root directory'), default=False)
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

    validate_root_directory = validate_root_directory

    def validate_name(self, field):
        project = db.session.scalar(
            select(Project).where(
                Project.name == field.data,
                Project.status != 'deleted'
            )
        )
        if project is not None:
            raise ValidationError(_('A project with this name already exists.'))

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_env_vars(self, formdata)
        process_commands_and_root_directory(self, formdata)


class DeleteProjectForm(FlaskForm):
    project_name = HiddenField(_l('Project Name'), validators=[DataRequired()])
    confirm = StringField(_l('Confirmation'), validators=[DataRequired()])
    submit = SubmitField(_l('Delete'), name='delete_project')

    def validate_confirm(self, field):
        if field.data != self.project_name.data:
            raise ValidationError(_('Project name confirmation did not match.'))


class DeployForm(FlaskForm):
    environment_slug = SelectField(_l('Environment'), choices=[], validators=[DataRequired()])
    commit = HiddenField(_l('Commit'), validators=[DataRequired()])
    submit = SubmitField(_l('Deploy'))

    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def validate_commit(self, field):
        branch, sha = field.data.split(':')

        if not branch or not sha:
            raise ValidationError(_('Invalid commit format.'))
        
        if not branch.strip():
            raise ValidationError(_('Branch cannot be empty.'))
        
        if not sha.strip():
            raise ValidationError(_('Commit SHA cannot be empty.'))
        
        if len(sha) != 40:
            raise ValidationError(_('Commit SHA must be 40 characters long.'))
        
        if not re.match(r'^[0-9a-fA-F]{40}$', sha):
            raise ValidationError(_('Invalid commit SHA format.'))

        environment = get_environment_for_branch(branch, self.project.active_environments)
        
        if not environment:
            raise ValidationError(_('Environment not found.'))
        
        if environment['slug'] != self.environment_slug.data:
            raise ValidationError(_('Environment does not match branch.'))