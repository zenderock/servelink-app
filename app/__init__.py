import logging
from flask import Flask, request, current_app
from flask_babel import Babel, lazy_gettext as _l
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
from app.services.github import GitHub
from datetime import datetime
import humanize
from redis import Redis
from rq import Queue


def get_locale():
    return request.accept_languages.best_match(current_app.config['LANGUAGES'])


db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = _l('Please sign in to access this page.')
babel = Babel()


def create_app(config_class=Config):
    app = Flask(__name__, static_url_path='')
    app.config.from_object(config_class)
    app.logger.setLevel(logging.INFO)
    app.github = GitHub(
        client_id=app.config['GITHUB_APP_CLIENT_ID'],
        client_secret=app.config['GITHUB_APP_CLIENT_SECRET'],
        app_id=app.config['GITHUB_APP_ID'],
        private_key=app.config['GITHUB_APP_PRIVATE_KEY']
    )
    redis_conn = Redis.from_url(app.config['REDIS_URL'])
    deployment_queue = Queue('deployments', connection=redis_conn)
    app.deployment_queue = deployment_queue

    def timeago(value):
        """Convert a datetime or ISO string to a human readable time ago."""
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return humanize.naturaltime(value)
    
    app.jinja_env.filters['timeago'] = timeago

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

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    return app


from app import models