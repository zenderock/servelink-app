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

from dependencies import get_translation as _, get_lazy_translation as _l
from models import Project, Team
from utils.color import COLORS


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
        _l("Name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z_][A-Za-z0-9_]*$",
                message=_l(
                    "Keys can only contain letters, numbers and underscores. They can not start with a number."
                ),
            ),
        ],
    )
    value = TextAreaField(_l("Value"), validators=[Optional()])
    environment = SelectField(
        _l("Environment"),
        default="",
        choices=[("", _l("All environments")), ("production", _l("Production"))],
    )
    delete = BooleanField(_l("Delete"), default=False)


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
                    _(
                        'Duplicate key "{key_name}" for environment "{env_name}".',
                        key_name=key_data,
                        env_name=env_data or _("All environments"),
                    )
                )
            else:
                processed_pairs.add(current_pair)

        if duplicates_found:
            raise ValidationError(_("Duplicate environment variable keys found."))


class ProjectEnvironmentForm(StarletteForm):
    environment_id = HiddenField()
    color = SelectField(
        _l("Color"),
        validators=[DataRequired()],
        choices=[(color, color) for color in COLORS],
    )
    name = StringField(_l("Name"), validators=[DataRequired(), Length(min=1, max=255)])
    slug = StringField(
        _l("Identifier"),
        validators=[
            DataRequired(),
            Length(min=1, max=255),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_l(
                    "Environment IDs can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    branch = StringField(
        _l("Branch"), validators=[DataRequired(), Length(min=1, max=255)]
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def validate_name(self, field):
        if self.environment_id.data:  # type: ignore
            env = self.project.get_environment_by_id(self.environment_id.data)  # type: ignore
            if env["slug"] == "production" and field.data != env["name"]:
                raise ValidationError(
                    _("The production environment name cannot be modified.")
                )

    def validate_slug(self, field):
        if self.environment_id.data:  # type: ignore
            env = self.project.get_environment_by_id(self.environment_id.data)  # type: ignore
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
    confirm = StringField(_l("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_l("Delete"))

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project

    def validate_confirm(self, field):
        environment = self.project.get_environment_by_id(self.environment_id.data)  # type: ignore
        if not environment:
            raise ValidationError(_("Environment not found."))
        if field.data != environment["slug"]:
            raise ValidationError(
                _("Environment identifier confirmation did not match.")
            )


class ProjectBuildAndProjectDeployForm(StarletteForm):
    framework = SelectField(
        _l("Framework presets"),
        choices=[
            ("flask", "Flask"),
            ("django", "Django"),
            ("fastapi", "FastAPI"),
            ("python", "Python"),
        ],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    runtime = SelectField(
        _l("Runtime"),
        choices=[("python-3", "Python 3"), ("python-2", "Python 2"), ("pypy", "PyPy")],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    use_custom_root_directory = BooleanField(_l("Custom root directory"), default=False)
    root_directory = StringField(
        _l("Root directory"),
        validators=[
            Length(max=255, message=_l("Root directory cannot exceed 255 characters")),
            Regexp(
                r"^[a-zA-Z0-9_\-./]*$",
                message=_l(
                    "Root directory can only contain letters, numbers, dots, hyphens, underscores, and forward slashes"
                ),
            ),
        ],
    )
    use_custom_build_command = BooleanField(_l("Custom build command"), default=False)
    use_custom_pre_deploy_command = BooleanField(
        _l("Custom pre-deploy command"), default=False
    )
    use_custom_start_command = BooleanField(_l("Custom start command"), default=False)
    build_command = StringField(_l("Build command"))
    pre_deploy_command = StringField(_l("Pre-deploy command"))
    start_command = StringField(_l("Start command"))

    validate_root_directory = validate_root_directory

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        super().process(formdata, obj, data, **kwargs)
        process_commands_and_root_directory(self, formdata)


class ProjectGeneralForm(StarletteForm):
    name = StringField(
        _l("Project name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_l(
                    "Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    avatar = FileField(_l("Avatar"))
    delete_avatar = BooleanField(_l("Delete avatar"), default=False)
    repo_id = IntegerField(_l("Repo ID"), validators=[DataRequired()])

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
                    raise ValidationError(
                        _("A project with this name already exists in this team.")
                    )


class NewProjectForm(StarletteForm):
    name = StringField(
        _l("Project name"),
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(
                r"^[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]$",
                message=_l(
                    "Project names can only contain letters, numbers, hyphens, underscores and dots. They cannot start or end with a dot, underscore or hyphen."
                ),
            ),
        ],
    )
    repo_id = IntegerField(_l("Repo ID"), validators=[DataRequired()])
    production_branch = StringField(
        _l("Production branch"), validators=[DataRequired(), Length(min=1, max=255)]
    )
    framework = SelectField(
        _l("Framework presets"),
        choices=[
            ("flask", "Flask"),
            ("django", "Django"),
            ("fastapi", "FastAPI"),
            ("python", "Python"),
        ],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    runtime = SelectField(
        _l("Runtime"),
        choices=[("python-3", "Python 3"), ("python-2", "Python 2"), ("pypy", "PyPy")],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    use_custom_root_directory = BooleanField(_l("Custom root directory"), default=False)
    root_directory = StringField(
        _l("Root directory"),
        validators=[
            Length(max=255, message=_l("Root directory cannot exceed 255 characters")),
            Regexp(
                r"^[a-zA-Z0-9_\-./]*$",
                message=_l(
                    "Root directory can only contain letters, numbers, dots, hyphens, underscores, and forward slashes"
                ),
            ),
        ],
    )
    use_custom_build_command = BooleanField(_l("Custom build command"), default=False)
    use_custom_pre_deploy_command = BooleanField(
        _l("Custom pre-deploy command"), default=False
    )
    use_custom_start_command = BooleanField(_l("Custom start command"), default=False)
    build_command = StringField(_l("Build command"))
    pre_deploy_command = StringField(_l("Pre-deploy command"))
    start_command = StringField(_l("Start command"))
    env_vars = FieldList(FormField(ProjectEnvVarForm))
    submit = SubmitField(_l("Save"))

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
                raise ValidationError(
                    _("A project with this name already exists in this team.")
                )


class ProjectDeleteForm(StarletteForm):
    name = HiddenField(_l("Project Name"), validators=[DataRequired()])
    confirm = StringField(_l("Confirmation"), validators=[DataRequired()])
    submit = SubmitField(_l("Delete"), name="delete_project")

    def validate_confirm(self, field):
        if field.data != self.name.data:  # type: ignore
            raise ValidationError(_("Project name confirmation did not match."))


class ProjectDeployForm(StarletteForm):
    commit = HiddenField(_l("Commit"), validators=[DataRequired()])
    submit = SubmitField(_l("Deploy"))


class ProjectRollbackForm(StarletteForm):
    environment_id = HiddenField(_l("Environment ID"), validators=[DataRequired()])
    submit = SubmitField(_l("Rollback"))


class ProjectPromoteForm(StarletteForm):
    environment_id = HiddenField(_l("Environment ID"), validators=[DataRequired()])
    deployment_id = HiddenField(_l("Deployment ID"), validators=[DataRequired()])
    submit = SubmitField(_l("Promote"))
