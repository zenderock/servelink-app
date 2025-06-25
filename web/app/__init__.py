import logging
from flask import Flask, request, current_app, get_flashed_messages, g
from jinja2 import ChoiceLoader, FileSystemLoader, FileSystemBytecodeCache
from flask_babel import Babel, lazy_gettext as _l
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
from app.services.github import GitHub
from datetime import datetime
import humanize
from redis import Redis
from rq import Queue
import json
import os
import time


def get_locale():
    return request.accept_languages.best_match(current_app.config['LANGUAGES'])


naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
metadata = MetaData(naming_convention=naming_convention)
db = SQLAlchemy(metadata=metadata)
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = _l('Please sign in to access this page.')
babel = Babel()


def create_app(config_class=Config):
    app = Flask(__name__)

    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,  # Flask's default loader (handles app & blueprint templates)
        FileSystemLoader('../shared/templates')
    ])

    app.config.from_object(config_class)
    app.logger.setLevel(logging.INFO)
    app.github = GitHub(
        client_id=app.config['GITHUB_APP_CLIENT_ID'],
        client_secret=app.config['GITHUB_APP_CLIENT_SECRET'],
        app_id=app.config['GITHUB_APP_ID'],
        private_key=app.config['GITHUB_APP_PRIVATE_KEY']
    )
    app.redis_client = Redis.from_url(app.config['REDIS_URL'])
    app.deployment_queue = Queue('deployments', connection=app.redis_client)
    
    # Load settings for frameworks presets
    project_root = os.path.dirname(app.root_path)
    settings_path = os.path.join(project_root, 'settings', 'frameworks.json')
    with open(settings_path) as f:
        app.frameworks = json.load(f)

    # Time ago filter (e.g. "just now", "1 hour ago", "2 days ago")
    def timeago(value):
        """Convert a datetime or ISO string to a human readable time ago."""
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return humanize.naturaltime(value)    
    app.jinja_env.filters['timeago'] = timeago

    # Escape strings for JavaScript
    def js_escape(value):
        return (
            value.replace('\\', '\\\\')
                .replace('"', '\\"')
                .replace("'", "\\'")
                .replace('\n', '')
                .replace('\r', '')
        )
    app.jinja_env.filters['js_escape'] = js_escape

    cache_dir = "/tmp/jinja-cache"
    os.makedirs(cache_dir, exist_ok=True)
    app.jinja_env.bytecode_cache = FileSystemBytecodeCache(cache_dir)

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    from app.errors import bp as errors_bp
    app.register_blueprint(errors_bp)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.team import bp as team_bp
    app.register_blueprint(team_bp)

    # from app.cli import register_commands
    # register_commands(app)

    @app.template_global()
    def get_flashed_toasts():
        return [
            {"category": c, "title": m}
            for c, m in get_flashed_messages(with_categories=True)
        ]

    @app.before_request
    def _t0(): g.t0 = time.perf_counter()

    @app.after_request
    def _t1(resp):
        dt = (time.perf_counter() - g.t0) * 1000
        app.logger.info("%s %.1f ms", request.path, dt)
        return resp

    app.config["SQLALCHEMY_RECORD_QUERIES"] = True
    from flask_sqlalchemy.record_queries import get_recorded_queries
    @app.after_request
    def _sql(resp):
        for q in get_recorded_queries():
            if q.duration > 0.02:  # 20 ms
                app.logger.info("⚠️  %.0f ms: %s", q.duration*1000, q.statement)
        return resp

    return app


from app import models