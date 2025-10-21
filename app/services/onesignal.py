import httpx
import logging
from typing import Dict, Any, List, Optional
from config import Settings

logger = logging.getLogger(__name__)


class OneSignalService:
    """Service for sending emails via OneSignal API."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_url = "https://api.onesignal.com/notifications?c=email"
        self.users_api_url = f"https://api.onesignal.com/apps/{settings.onesignal_app_id}/users"
        # Different headers for different APIs
        self.notification_headers = {
            "Authorization": f"Key {settings.onesignal_api_key}",
            "Content-Type": "application/json"
        }
        # For users API, we might need a different key or format
        self.users_headers = {
            "Authorization": f"Key {settings.onesignal_api_key}",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient()
    
    async def register_subscriber(
        self,
        email: str,
        user_id: Optional[str] = None,
        external_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register a user as a subscriber in OneSignal.
        
        Args:
            email: User's email address
            user_id: Optional user ID for tracking
            external_id: Optional external ID for tracking
            
        Returns:
            Dict containing the response from OneSignal API
        """
        payload = {
            "subscriptions": [
                {
                    "type": "Email",
                    "token": email,
                    "enabled": True
                }
            ]
        }
        
        # Add optional user identification
        if user_id:
            payload["identity"] = {"user_id": user_id}
        if external_id:
            payload["external_id"] = external_id
        
        try:
            response = await self.client.post(
                self.users_api_url,
                headers=self.users_headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"User {email} registered as subscriber successfully")
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OneSignal API error registering subscriber: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to register subscriber: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"OneSignal request error registering subscriber: {str(e)}")
            raise Exception(f"Failed to register subscriber: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error registering subscriber: {str(e)}")
            raise
    
    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        from_name: Optional[str] = None,
        from_address: Optional[str] = None,
        reply_to: Optional[str] = None,
        preheader: Optional[str] = None,
        custom_data: Optional[Dict[str, Any]] = None,
        auto_register: bool = True
    ) -> Dict[str, Any]:
        """
        Send an email via OneSignal.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML content of the email
            from_name: Sender name (defaults to settings.email_sender_name)
            from_address: Sender email (defaults to settings.email_sender_address)
            reply_to: Reply-to email address
            preheader: Preview text for the email
            custom_data: Additional custom data to include
            auto_register: Whether to automatically register the user as a subscriber
            
        Returns:
            Dict containing the response from OneSignal API
        """
        # Register user as subscriber first if auto_register is enabled
        if auto_register:
            try:
                await self.register_subscriber(to_email)
            except Exception as e:
                logger.warning(f"Failed to register subscriber {to_email}: {str(e)}. Continuing with email send...")
        payload = {
            "app_id": self.settings.onesignal_app_id,
            "email_to": [to_email],
            "target_channel": "email",
            "email_subject": subject,
            "email_body": html_content,
            "email_from_name": from_name or self.settings.email_sender_name,
            "email_from_address": from_address or self.settings.email_sender_address,
        }
        
        # Add optional fields if provided
        if reply_to:
            payload["email_reply_to_address"] = reply_to
        
        if preheader:
            payload["email_preheader"] = preheader
            
        if custom_data:
            payload["custom_data"] = custom_data
        
        try:
            response = await self.client.post(
                self.api_url,
                headers=self.notification_headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Email sent successfully to {to_email}, message ID: {result.get('id', 'unknown')}")
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OneSignal API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to send email: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"OneSignal request error: {str(e)}")
            raise Exception(f"Failed to send email: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error sending email: {str(e)}")
            raise
    
    async def send_bulk_email(
        self,
        to_emails: List[str],
        subject: str,
        html_content: str,
        from_name: Optional[str] = None,
        from_address: Optional[str] = None,
        reply_to: Optional[str] = None,
        preheader: Optional[str] = None,
        custom_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send bulk emails via OneSignal (up to 20,000 recipients).
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            html_content: HTML content of the email
            from_name: Sender name (defaults to settings.email_sender_name)
            from_address: Sender email (defaults to settings.email_sender_address)
            reply_to: Reply-to email address
            preheader: Preview text for the email
            custom_data: Additional custom data to include
            
        Returns:
            Dict containing the response from OneSignal API
        """
        if len(to_emails) > 20000:
            raise ValueError("OneSignal supports maximum 20,000 recipients per request")
        
        payload = {
            "app_id": self.settings.onesignal_app_id,
            "email_to": to_emails,
            "target_channel": "email",
            "email_subject": subject,
            "email_body": html_content,
            "email_from_name": from_name or self.settings.email_sender_name,
            "email_from_address": from_address or self.settings.email_sender_address,
        }
        
        # Add optional fields if provided
        if reply_to:
            payload["email_reply_to_address"] = reply_to
        
        if preheader:
            payload["email_preheader"] = preheader
            
        if custom_data:
            payload["custom_data"] = custom_data
        
        try:
            response = await self.client.post(
                self.api_url,
                headers=self.notification_headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Bulk email sent successfully to {len(to_emails)} recipients, message ID: {result.get('id', 'unknown')}")
            return result
            
        except httpx.HTTPStatusError as e:
            logger.error(f"OneSignal API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Failed to send bulk email: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"OneSignal request error: {str(e)}")
            raise Exception(f"Failed to send bulk email: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error sending bulk email: {str(e)}")
            raise
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
