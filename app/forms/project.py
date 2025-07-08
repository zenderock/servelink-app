from starlette_wtf import StarletteForm
from wtforms import (
    StringField,
    IntegerField,
    SelectField,
    SubmitField,
    FieldList,
    FormField,
    Form,
    BooleanField,
    FileField,
    HiddenField,
    TextAreaField,
)
from wtforms.validators import ValidationError, DataRequired, Length, Regexp, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import get_translation as _
from models import Project, Team
from utils.colors import COLORS
from utils.environments import get_environment_for_branch
import re


def validate_root_directory(form, field):
    if field.data:
        path = field.data.strip().strip("/")
        if ".." in path or "/./" in path or "/../" in path:
            raise ValidationError(
                _(
                    "Invalid path: must be a valid subdirectory relative to repository root"
                )
            )
        if "//" in path:
            raise ValidationError(_("Invalid path: cannot contain consecutive slashes"))
        field.data = path


def process_env_vars(form, formdata):
    if not hasattr(form, "env_vars"):
        return

    filtered = [
        e
        for e in form.env_vars.entries
        if not e.delete.data and (e.key.data.strip() or e.value.data.strip())
    ]
    
    form.env_vars.entries = filtered
    form.env_vars._fields = {str(i): e for i, e in enumerate(filtered)}


def process_commands_and_root_directory(form, formdata):
    if formdata:
        if (
            hasattr(form, "use_custom_build_command")
            and not form.use_custom_build_command.data
        ):
            form.build_command.data = None
        if (
            hasattr(form, "use_custom_pre_deploy_command")
            and not form.use_custom_pre_deploy_command.data
        ):
            form.pre_deploy_command.data = None
        if (
            hasattr(form, "use_custom_start_command")
            and not form.use_custom_start_command.data
        ):
            form.start_command.data = None
        if (
            hasattr(form, "use_custom_root_directory")
            and not form.use_custom_root_directory.data
        ):
            form.root_directory.data = None


class ProjectEnvVarForm(Form):
    env_var_id = HiddenField()
    key = StringField(
        _("Name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z_][A-Za-z0-9_]*$",
                message=_(
                    "Keys can only contain letters, numbers and underscores. They can not start with a number."
                ),
            ),
        ],
    )
    value = TextAreaField(_("Value"), validators=[Optional()])
    environment = SelectField(_("Environment"), default="", choices=[
        ("", _("All environments")),
        ("production", _("Production"))
    ])
    delete = BooleanField(_("Delete"), default=False)


class ProjectEnvVarsForm(StarletteForm):
    env_vars = FieldList(FormField(ProjectEnvVarForm), min_entries=0)

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_env_vars(self, formdata)

    def validate_env_vars(self, field):
        processed_pairs = set()
        duplicates_found = False

        for entry_form in field.entries:
            key_data = entry_form.key.data
            env_data = entry_form.environment.data

            if key_data is None:
                continue

            current_pair = (key_data.strip(), env_data.strip())

            if current_pair in processed_pairs:
                duplicates_found = True
                entry_form.key.errors.append(
                    _('Duplicate key "{}" for environment "{}".').format(
                        key_data, env_data or _("All environments")
                    )
                )
            else:
                processed_pairs.add(current_pair)

        if duplicates_found:
            raise ValidationError(_("Duplicate environment variable keys found."))


class ProjectEnvironmentForm(StarletteForm):
    environment_id = HiddenField()
    color = SelectField(
        _("Color"),
        validators=[DataRequired()],
        choices=[(color, color) for color in COLORS],
    )
    name = StringField(_("Name"), validators=[DataRequired(), Length(min=1, max=255)])
    slug = StringField(
        _("Identifier"),
        validators=[
            DataRequired(),
            Length(min=1, max=255),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_(
                    "Environment IDs can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    branch = StringField(
        _("Branch"), validators=[DataRequired(), Length(min=1, max=255)]
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def validate_name(self, field):
        if self.environment_id.data: # type: ignore
            env = self.project.get_environment_by_id(self.environment_id.data) # type: ignore
            if env["slug"] == "production" and field.data != env["name"]:
                raise ValidationError(
                    _("The production environment name cannot be modified.")
                )

    def validate_slug(self, field):
        if self.environment_id.data: # type: ignore
            env = self.project.get_environment_by_id(self.environment_id.data) # type: ignore
            if field.data == env["slug"]:
                return

            if env["slug"] == "production":
                raise ValidationError(
                    _("The production environment identifier cannot be modified.")
                )

        # New environment
        if self.project.has_active_environment_with_slug(field.data):
            raise ValidationError(
                _("This identifier is already in use by another environment.")
            )


class ProjectDeleteEnvironmentForm(StarletteForm):
    environment_id = HiddenField(validators=[DataRequired()])
    confirm = StringField(_("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_("Delete"))

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def validate_confirm(self, field):
        environment = self.project.get_environment_by_id(self.environment_id.data) # type: ignore
        if not environment:
            raise ValidationError(_("Environment not found."))
        if field.data != environment["slug"]:
            raise ValidationError(
                _("Environment identifier confirmation did not match.")
            )


class ProjectBuildAndProjectDeployForm(StarletteForm):
    framework = SelectField(
        _("Framework presets"),
        choices=[
            ("flask", "Flask"),
            ("django", "Django"),
            ("fastapi", "FastAPI"),
            ("python", "Python"),
        ],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    runtime = SelectField(
        _("Runtime"),
        choices=[("python-3", "Python 3"), ("python-2", "Python 2"), ("pypy", "PyPy")],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    use_custom_root_directory = BooleanField(_("Custom root directory"), default=False)
    root_directory = StringField(
        _("Root directory"),
        validators=[
            Length(max=255, message=_("Root directory cannot exceed 255 characters")),
            Regexp(
                r"^[a-zA-Z0-9_\-./]*$",
                message=_(
                    "Root directory can only contain letters, numbers, dots, hyphens, underscores, and forward slashes"
                ),
            ),
        ],
    )
    use_custom_build_command = BooleanField(_("Custom build command"), default=False)
    use_custom_pre_deploy_command = BooleanField(
        _("Custom pre-deploy command"), default=False
    )
    use_custom_start_command = BooleanField(_("Custom start command"), default=False)
    build_command = StringField(_("Build command"))
    pre_deploy_command = StringField(_("Pre-deploy command"))
    start_command = StringField(_("Start command"))

    validate_root_directory = validate_root_directory

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_commands_and_root_directory(self, formdata)


class ProjectGeneralForm(StarletteForm):
    name = StringField(
        _("Project name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_(
                    "Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    avatar = FileField(_("Avatar"))
    delete_avatar = BooleanField(_("Delete avatar"), default=False)
    repo_id = IntegerField(_("Repo ID"), validators=[DataRequired()])

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

    def __init__(self, *args, db: AsyncSession, team: Team, project: Project, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.team = team
        self.project = project

    async def async_validate_name(self, field):
        if self.db and self.team and self.project:
            if self.project.name != field.data:
                result = await self.db.execute(
                    select(Project).where(
                        func.lower(Project.name) == field.data.lower(),
                        Project.team_id == self.team.id,
                        Project.status != "deleted",
                        Project.id != self.project.id,
                    )
                )
                if result.scalar_one_or_none():
                    raise ValidationError(_("A project with this name already exists in this team."))


class NewProjectForm(StarletteForm):
    name = StringField(
        _("Project name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_(
                    "Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    repo_id = IntegerField(_("Repo ID"), validators=[DataRequired()])
    production_branch = StringField(
        _("Production branch"), validators=[DataRequired(), Length(min=1, max=255)]
    )
    framework = SelectField(
        _("Framework presets"),
        choices=[
            ("flask", "Flask"),
            ("django", "Django"),
            ("fastapi", "FastAPI"),
            ("python", "Python"),
        ],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    runtime = SelectField(
        _("Runtime"),
        choices=[("python-3", "Python 3"), ("python-2", "Python 2"), ("pypy", "PyPy")],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    use_custom_root_directory = BooleanField(_("Custom root directory"), default=False)
    root_directory = StringField(
        _("Root directory"),
        validators=[
            Length(max=255, message=_("Root directory cannot exceed 255 characters")),
            Regexp(
                r"^[a-zA-Z0-9_\-./]*$",
                message=_(
                    "Root directory can only contain letters, numbers, dots, hyphens, underscores, and forward slashes"
                ),
            ),
        ],
    )
    use_custom_build_command = BooleanField(_("Custom build command"), default=False)
    use_custom_pre_deploy_command = BooleanField(
        _("Custom pre-deploy command"), default=False
    )
    use_custom_start_command = BooleanField(_("Custom start command"), default=False)
    build_command = StringField(_("Build command"))
    pre_deploy_command = StringField(_("Pre-deploy command"))
    start_command = StringField(_("Start command"))
    env_vars = FieldList(FormField(ProjectEnvVarForm))
    submit = SubmitField(_("Save"))

    validate_root_directory = validate_root_directory

    def __init__(self, *args, db: AsyncSession, team: Team, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.team = team

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_env_vars(self, formdata)
        process_commands_and_root_directory(self, formdata)

    async def async_validate_name(self, field):
        if self.db and self.team:
            result = await self.db.execute(
                select(Project).where(
                    func.lower(Project.name) == field.data.lower(),
                    Project.team_id == self.team.id,
                    Project.status != "deleted",
                )
            )
            if result.scalar_one_or_none():
                raise ValidationError(_("A project with this name already exists in this team."))


class ProjectDeleteForm(StarletteForm):
    name = HiddenField(_("Project Name"), validators=[DataRequired()])
    confirm = StringField(_("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_("Delete"), name="delete_project")

    def validate_confirm(self, field):
        if field.data != self.name.data: # type: ignore
            raise ValidationError(_("Project name confirmation did not match."))


class ProjectDeployForm(StarletteForm):
    environment_id = SelectField(
        _("Environment"), choices=[], validators=[DataRequired()]
    )
    commit = HiddenField(_("Commit"), validators=[DataRequired()])
    submit = SubmitField(_("Deploy"))

    def __init__(self, *args, project: Project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    async def async_validate_commit(self, field):
        branch, sha = field.data.split(":")

        if not branch or not sha:
            raise ValidationError(_("Invalid commit format."))

        if not branch.strip():
            raise ValidationError(_("Branch cannot be empty."))

        if not sha.strip():
            raise ValidationError(_("Commit SHA cannot be empty."))

        if len(sha) != 40:
            raise ValidationError(_("Commit SHA must be 40 characters long."))

        if not re.match(r"^[0-9a-fA-F]{40}$", sha):
            raise ValidationError(_("Invalid commit SHA format."))

        environment = get_environment_for_branch(
            branch, self.project.active_environments
        )

        if not environment:
            raise ValidationError(_("Environment not found."))

        if environment["id"] != self.environment_id.data: # type: ignore
            raise ValidationError(_("Environment does not match branch."))
