from starlette_wtf import StarletteForm
from wtforms import (
    StringField,
    IntegerField,
    DecimalField,
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
from wtforms.validators import (
    ValidationError,
    DataRequired,
    Length,
    Regexp,
    Optional,
    NumberRange,
)
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import re
from starlette.datastructures import FormData

from dependencies import get_translation as _, get_lazy_translation as _l
from config import get_settings
from models import Project, Team, Domain
from utils.color import COLORS


def validate_image(self, field):
    preset_image = next(
        (
            preset["image"]
            for preset in self._presets
            if preset["slug"] == self.preset.data
        ),
        None,
    )
    if not preset_image:
        return
    image_group = self._images.get(preset_image)
    if not image_group:
        return
    if self.image.data and self.image.data not in {
        image["slug"] for image in image_group
    }:
        raise ValidationError(
            _("Invalid image for this preset. Please select an image from the list.")
        )


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


def _normalize_env_vars_formdata(formdata):
    def getlist(key):
        try:
            return formdata.getlist(key)
        except AttributeError:
            value = formdata.get(key)
            if value is None:
                return []
            return value if isinstance(value, list) else [value]

    indexes = set()
    for key in formdata:
        match = re.match(r"env_vars-(\d+)-", key)
        if match:
            indexes.add(int(match.group(1)))

    pairs = []
    new_i = 0

    for i in sorted(indexes):
        if getlist(f"env_vars-{i}-delete"):
            continue

        key_value = (getlist(f"env_vars-{i}-key") or [""])[0]
        value_value = (getlist(f"env_vars-{i}-value") or [""])[0]
        environment_value = (getlist(f"env_vars-{i}-environment") or [""])[0]

        if key_value or value_value:
            pairs.append((f"env_vars-{new_i}-key", key_value))
            pairs.append((f"env_vars-{new_i}-value", value_value))
            pairs.append((f"env_vars-{new_i}-environment", environment_value))
            new_i += 1

    for key in formdata:
        if not key.startswith("env_vars-"):
            for value in getlist(key):
                pairs.append((key, value))

    return FormData(pairs)


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
        if formdata is not None:
            formdata = _normalize_env_vars_formdata(formdata)
        super().process(formdata, obj, data, **kwargs)

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
                        'Duplicate key "%(key_name)s" for environment "%(env_name)s".',
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


class ProjectResourcesForm(StarletteForm):
    cpus = DecimalField(
        _l("CPUs"),
        validators=[Optional()],  # Validation custom dans router
    )
    memory = IntegerField(
        _l("Memory (MB)"),
        validators=[Optional()],  # Validation custom dans router
    )
    
    async def validate_with_plan(self, team, db, project_id: str = None):
        """Validation selon le plan de l'équipe"""
        from services.pricing import ResourceValidationService
        service = ResourceValidationService()
        valid, msg = await service.validate_resources(
            team, self.cpus.data, self.memory.data, db, project_id
        )
        if not valid:
            if self.cpus.data and team.current_plan and self.cpus.data > team.current_plan.max_cpu_cores:
                self.cpus.errors.append(msg)
            if self.memory.data and team.current_plan and self.memory.data > team.current_plan.max_memory_mb:
                self.memory.errors.append(msg)
        return valid


class ProjectDomainForm(StarletteForm):
    domain_id = HiddenField()
    hostname = StringField(
        _l("Domain"),
        validators=[
            DataRequired(),
            Length(min=1, max=255),
            Regexp(
                r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
                message=_l("Please enter a valid domain name"),
            ),
        ],
    )
    type = SelectField(
        _l("Type"),
        validators=[DataRequired()],
        choices={
            _l("Routing"): [("route", _l("Route"))],
            _l("Permanent Redirect"): [
                ("301", _l("301 - Moved Permanently")),
                ("308", _l("308 - Permanent Redirect")),
            ],
            _l("Temporary Redirect"): [
                ("302", _l("302 - Found")),
                ("307", _l("307 - Temporary Redirect")),
            ],
        },
    )
    environment_id = SelectField(_l("Environment"), choices=[])

    def __init__(
        self,
        *args,
        project: Project,
        domains: list[Domain] | None = None,
        db: AsyncSession,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.project = project
        self.domains = domains or []
        self.db = db

        self.environment_id.choices = [
            (env["id"], env["name"]) for env in project.active_environments
        ]

    async def async_validate_hostname(self, field):
        if field.data:
            query = select(Domain).where(
                func.lower(Domain.hostname) == field.data.lower()
            )
            if self.domain_id.data:
                query = query.where(Domain.id != int(self.domain_id.data))
            result = await self.db.execute(query)
            domain = result.scalar_one_or_none()
            if domain:
                raise ValidationError(_("This domain is already in use."))

    def validate_environment_id(self, field):
        if self.type.data == "route" and not field.data:
            raise ValidationError(_("Environment is required for routing type."))

        if field.data:
            environment = self.project.get_environment_by_id(field.data)
            if not environment:
                raise ValidationError(_("Environment not found."))


class ProjectRemoveDomainForm(StarletteForm):
    domain_id = HiddenField(validators=[DataRequired()])
    confirm = StringField(_l("Confirmation"), validators=[DataRequired()])

    def __init__(self, *args, project: Project, domains: list[Domain], **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.domains = domains

    def validate_domain_id(self, field):
        domain = next(
            (domain for domain in self.domains if domain.id == int(field.data)), None
        )
        if not domain:
            raise ValidationError(_("Domain not found."))

    def validate_confirm(self, field):
        domain = next(
            (
                domain
                for domain in self.domains
                if domain.id == int(self.domain_id.data)
            ),
            None,
        )
        if not domain:
            raise ValidationError(_("Domain not found."))
        if field.data != domain.hostname:
            raise ValidationError(_("Domain confirmation did not match."))


class ProjectVerifyDomainForm(StarletteForm):
    domain_id = HiddenField(validators=[DataRequired()])

    def __init__(self, *args, domains: list[Domain], **kwargs):
        super().__init__(*args, **kwargs)
        self.domains = domains

    def validate_domain_id(self, field):
        domain = next(
            (domain for domain in self.domains if domain.id == int(field.data)), None
        )
        if not domain:
            raise ValidationError(_("Domain not found."))
        if domain.status == "active":
            raise ValidationError(_("Domain is already verified."))


class ProjectBuildAndProjectDeployForm(StarletteForm):
    preset = SelectField(
        _l("Framework presets"),
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    image = SelectField(
        _l("Image"),
        validators=[DataRequired(), Length(min=1, max=255)],
    )
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
    build_command = StringField(_l("Build command"))
    pre_deploy_command = StringField(_l("Pre-deploy command"))
    start_command = StringField(
        _l("Start command"), validators=[DataRequired(), Length(min=1)]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        settings = get_settings()
        self._images = settings.images
        self._presets = settings.presets
        self.preset.choices = [
            (preset["slug"], preset["name"]) for preset in self._presets
        ]
        self.image.choices = {
            group: [(image["slug"], image["name"]) for image in items]
            for group, items in self._images.items()
        }

    def validate_preset(self, field):
        preset = next(
            (p for p in self._presets if p["slug"] == field.data),
            None
        )
        if preset and preset.get("disabled"):
            raise ValidationError(
                _("This framework is currently unavailable.")
            )

    validate_image = validate_image

    validate_root_directory = validate_root_directory


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
    preset = SelectField(
        _l("Framework presets"),
        choices=[],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    image = SelectField(
        _l("Image"),
        choices=[],
        validators=[DataRequired(), Length(min=1, max=255)],
    )
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
    build_command = StringField(_l("Build command"))
    pre_deploy_command = StringField(_l("Pre-deploy command"))
    start_command = StringField(
        _l("Start command"), validators=[DataRequired(), Length(min=1)]
    )
    env_vars = FieldList(FormField(ProjectEnvVarForm))
    submit = SubmitField(_l("Save"))

    validate_root_directory = validate_root_directory

    def __init__(self, *args, db: AsyncSession, team: Team, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = db
        self.team = team
        settings = get_settings()
        self._images = settings.images
        self._presets = settings.presets
        self.preset.choices = [
            (preset["slug"], preset["name"]) for preset in self._presets
        ]
        self.image.choices = {
            group: [(image["slug"], image["name"]) for image in items]
            for group, items in self._images.items()
        }

    def process(self, formdata=None, obj=None, data=None, **kwargs):
        if formdata is not None:
            formdata = _normalize_env_vars_formdata(formdata)
        super().process(formdata, obj, data, **kwargs)
        # process_commands_and_root_directory(self, formdata)

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

    def validate_preset(self, field):
        preset = next(
            (p for p in self._presets if p["slug"] == field.data),
            None
        )
        if preset and preset.get("disabled"):
            raise ValidationError(
                _("This framework is currently unavailable.")
            )

    validate_image = validate_image


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


class ProjectCancelDeploymentForm(StarletteForm):
    submit = SubmitField(_l("Cancel"))


class ProjectRollbackDeploymentForm(StarletteForm):
    environment_id = HiddenField(_l("Environment ID"), validators=[DataRequired()])
    submit = SubmitField(_l("Rollback"))


class ProjectPromoteDeploymentForm(StarletteForm):
    environment_id = HiddenField(_l("Environment ID"), validators=[DataRequired()])
    deployment_id = HiddenField(_l("Deployment ID"), validators=[DataRequired()])
    submit = SubmitField(_l("Promote"))
