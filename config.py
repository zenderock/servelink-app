import os
from dotenv import load_dotenv


basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'), override=True)


class Config(object):
    APP_NAME = os.environ.get('APP_NAME', 'App name')
    APP_DESCRIPTION = os.environ.get('APP_DESCRIPTION', 'App description')
    APP_SOCIAL_IMAGE = os.environ.get('APP_SOCIAL_IMAGE', '/social.png')
    LANGUAGES = ['en']
    SECRET_KEY = os.environ.get('SECRET_KEY', 'random-unique-secret-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'app.db'))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SENDER_NAME = os.environ.get('MAIL_SENDER_NAME', APP_NAME)
    MAIL_SENDER_EMAIL = os.environ.get('MAIL_SENDER_EMAIL', 'noreply@example.com')
    MAIL_LOGO = os.environ.get('MAIL_LOGO', '/assets/logo/logo-72x72.png')
    MAIL_FOOTER = os.environ.get('MAIL_FOOTER')
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    GITHUB_APP_ID = os.environ.get('GITHUB_APP_ID')
    GITHUB_APP_NAME = os.environ.get('GITHUB_APP_NAME')
    GITHUB_APP_PRIVATE_KEY = os.environ.get('GITHUB_APP_PRIVATE_KEY')
    GITHUB_APP_WEBHOOK_SECRET = os.environ.get('GITHUB_APP_WEBHOOK_SECRET')
    GITHUB_APP_CLIENT_ID = os.environ.get('GITHUB_APP_CLIENT_ID')
    GITHUB_APP_CLIENT_SECRET = os.environ.get('GITHUB_APP_CLIENT_SECRET')
    TEMPLATES_AUTO_RELOAD = os.environ.get('TEMPLATES_AUTO_RELOAD') or False
    ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
    if not ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY must be set")
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    BASE_DOMAIN = os.environ.get('BASE_DOMAIN', 'localhost')