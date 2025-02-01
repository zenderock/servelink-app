import requests
import jwt
import time
from datetime import datetime, timedelta

class GitHub:
    def __init__(self, client_id: str, client_secret: str, app_id: str, private_key: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.app_id = app_id
        self.private_key = private_key
        self._jwt_token = None
        self._jwt_expires_at = None

    @property
    def jwt_token(self) -> str:
        """Get a valid JWT token, generating a new one if needed."""
        now = int(time.time())
        
        # Generate new token if none exists or current one is expiring soon
        if (not self._jwt_token or 
            not self._jwt_expires_at or 
            self._jwt_expires_at - now < 60):  # Buffer of 1 minute
            
            # Token expires in 10 minutes
            self._jwt_expires_at = now + (10 * 60)
            self._jwt_token = jwt.encode(
                {
                    'iat': now,
                    'exp': self._jwt_expires_at,
                    'iss': self.app_id
                },
                self.private_key,
                algorithm='RS256'
            )
        
        return self._jwt_token

    def get_user_access_token(self, code: str) -> str | None:
        """Exchange OAuth code for access token."""
        response = requests.post(
            'https://github.com/login/oauth/access_token',
            headers={'Accept': 'application/json'},
            data={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code,
            }
        )
        response.raise_for_status()
        return response.json().get('access_token')

    def get_user_info(self, user_access_token: str) -> tuple[str, str, str | None]:
        """Get user ID and username from GitHub."""
        response = requests.get(
            'https://api.github.com/user',
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        user_info = response.json()
        return (
            user_info.get('id'),
            user_info.get('login'),
            user_info.get('name')
        )

    def get_user_primary_email(self, user_access_token: str) -> str | None:
        """Get user's primary verified email."""
        response = requests.get(
            'https://api.github.com/user/emails',
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        email_data = response.json()
        primary_email = next(
            (e for e in email_data if e['primary'] and e['verified']),
            None
        )
        return primary_email.get('email') if primary_email else None
    
    def get_user_installations(self, user_access_token: str) -> list:
        """Get all installations the authenticated user has access to."""
        response = requests.get(
            'https://api.github.com/user/installations',
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        return response.json()['installations']

    def search_user_repositories(self, user_access_token: str, owner: str, keywords: str = "", per_page: int = 5) -> list[dict]:
        """Search repositories for a specific owner."""
        response = requests.get(
            'https://api.github.com/search/repositories',
            params={
                'q': f"{keywords} in:name org:{owner} fork:true".strip(),
                'per_page': per_page
            },
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        return response.json()['items']

    def get_repository(self, user_access_token: str, repo_id: int) -> dict:
        """Get a repository by its ID."""
        response = requests.get(
            f'https://api.github.com/repositories/{repo_id}',
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        return response.json()
    
    def get_repository_branches(self, user_access_token: str, repo_id: int) -> list:
        """Get branches for a repository using its ID."""
        response = requests.get(
            f'https://api.github.com/repositories/{repo_id}/branches',
            headers={'Authorization': f'Bearer {user_access_token}'}
        )
        response.raise_for_status()
        return response.json()

    def get_installation(self, installation_id: str) -> dict:
        """Get installation details from GitHub."""
        response = requests.get(
            f'https://api.github.com/app/installations/{installation_id}',
            headers={ 'Authorization': f'Bearer {self.jwt_token}' }
        )
        response.raise_for_status()
        return response.json()
    
    def get_installation_access_token(self, installation_id: str) -> dict[str, str | dict]:
        """Get an installation access token."""
        response = requests.post(
            f'https://api.github.com/app/installations/{installation_id}/access_tokens',
            headers={ 'Authorization': f'Bearer {self.jwt_token}' }
        )
        response.raise_for_status()
        return response.json()
    
    def get_installation_repositories(self, installation_access_token: str) -> list[dict]:
        """Get repositories for a specific installation."""
        response = requests.get(
            'https://api.github.com/installation/repositories',
            headers={ 'Authorization': f'Bearer {installation_access_token}' }
        )
        response.raise_for_status()
        return response.json()['repositories']  # Note: returns paginated response
