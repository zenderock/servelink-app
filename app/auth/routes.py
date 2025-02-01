from flask import render_template, redirect, url_for, flash, current_app, request, session
from urllib.parse import urlparse
from flask_login import login_user, logout_user, current_user
from app import db
from app.models import User, GithubInstallation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.auth import bp
# from app.auth.forms import LoginForm
# from app.auth.utils import send_login_email, verify_login_token
from flask_babel import _
from app.services.github import GitHub
from coolname import generate_slug
from secrets import token_urlsafe
from datetime import datetime


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@bp.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    # form = LoginForm()
    # if form.validate_on_submit():
    #     send_login_email(form.email.data)
    #     flash(_("We've sent you an email with a link to log in."))
    #     return redirect(url_for('main.index'))
    return render_template('auth/login.html')


@bp.route('/github')
def github_login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # Store next page if provided
    next_page = request.args.get('next')
    if next_page:
        session['next'] = next_page
    
    # Generate and store state
    state = token_urlsafe(32)
    session['github_state'] = state
    
    github_auth_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={current_app.config['GITHUB_APP_CLIENT_ID']}"
        f"&state={state}"
    )
    return redirect(github_auth_url)


@bp.route('/github/callback')
def github_callback():
    # Verify state
    state = request.args.get('state')
    expected_state = session.pop('github_state', None)
    if not state or state != expected_state:
        flash(_('Invalid state parameter'), 'error')
        current_app.logger.error(f"Invalid state parameter: received {state}, expected {expected_state}")
        return redirect(url_for('main.index'))

    # Installation flow
    if 'installation_id' in request.args:
        installation_id = request.args.get('installation_id')
        setup_action = request.args.get('setup_action')
        
        if setup_action in ['install', 'update']:  # Both handled the same
            try:
                data = current_app.github.get_installation(installation_id)
                token_data = current_app.github.get_installation_access_token(installation_id)
                
                installation = GithubInstallation(
                    installation_id=installation_id,
                    token=token_data['token'],
                    token_expires_at=datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
                )
                
                db.session.merge(installation)
                db.session.commit()

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error handling installation {installation_id}: {str(e)}")
                flash(_('Error processing installation'), 'error')
        else:
            flash(_('Invalid setup action'), 'error')
            current_app.logger.error(f"Invalid setup action: received {setup_action}")
    
    # OAuth login flow
    if 'code' in request.args:
        if current_user.is_authenticated:
            return redirect(url_for('main.index'))
    
        # Get the OAuth code from the query string
        code = request.args.get('code')
        if not code:
            flash(_('GitHub login failed: no code provided by GitHub.'), 'error')
            return redirect(url_for('auth.login'))

        # Get access token from GitHub
        try:
            access_token = current_app.github.get_user_access_token(code)
        except Exception as e:
            current_app.logger.error(f'Could not retrieve GitHub access token: {e}')
            flash(_('GitHub login failed: could not retrieve access token.'), 'error')
            return redirect(url_for('auth.login'))

        # Get user info from GitHub
        try:
            github_id, github_login, github_name = current_app.github.get_user_info(access_token)
        except Exception as e:
            current_app.logger.error(f'Could not retrieve GitHub user info: {e}')
            flash(_('GitHub login failed: could not retrieve user info.'), 'error')
            return redirect(url_for('auth.login'))

        # Check if user exists in the database
        user = db.session.scalar(
            select(User).where(User.github_id == github_id).limit(1)
        )
        if user is None:
            # Get primary email from GitHub
            try:
                email = current_app.github.get_user_primary_email(access_token)
            except Exception as e:
                current_app.logger.error(f'Could not retrieve GitHub primary email: {e}')
                flash(_('GitHub login failed: coould not retrieve primary email.'), 'error')
                return redirect(url_for('auth.login'))
            
            user = create_user(
                github_id=github_id,
                name=github_name,
                email=email,
                base_username=github_login,
                token=access_token
            );
            if user.username != login:
                flash(_('Your account was successfully created. Your username has been set to: %(username)s', username=user.username))
            else:
                flash(_('Your account was successfully created.'))
        else:
            user.github_token = access_token
            db.session.commit()

        login_user(user)

    next_page = request.args.get('next')
    if not next_page or urlparse(next_page).netloc != '':
        next_page = url_for('main.index')
    return redirect(next_page)


def create_user(github_id: str, base_username: str, token: str | None, name: str | None, email: str | None) -> User:
    """Create a user with a valid (unqiue) username."""
    attempt = 0
    while True:
        username = generate_slug(2) if attempt > 0 else base_username
        user = User(
            github_id=github_id,
            username=username,
            name=name,
            email=email,
            github_token=token
        )
        db.session.add(user)
        try:
            db.session.flush()
            db.session.commit()
            return user
        except IntegrityError as e:
            db.session.rollback()
            if 'username' in str(e.orig):
                attempt += 1
                if attempt > 5:
                    raise Exception("Could not generate unique username")
                continue
            raise
    
# @bp.route('/login/<token>', methods=['GET', 'POST'])
# def login_with_token(token):
#     if current_user.is_authenticated:
#         return redirect(url_for('main.index'))
#     email = verify_login_token(token)
#     if email is None:
#         flash(_('Invalid token.'))
#         return redirect(url_for('main.index'))
#     else:
#         user = db.session.scalar(
#             select(User).where(User.email == email).limit(1)
#         )
#         if user is None:
#             user = User(email=email)
#             db.session.add(user)
#             db.session.commit()
#             flash(_('Congratulations, you are now a registered user.'))
#         login_user(user)
#         next_page = request.args.get('next')
#         if not next_page or urlparse(next_page).netloc != '':
#             next_page = url_for('main.index')
#         return redirect(next_page)