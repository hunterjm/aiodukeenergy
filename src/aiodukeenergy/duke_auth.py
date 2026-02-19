"""
Duke Energy authentication classes.

This module provides abstract and concrete authentication classes that follow
the Home Assistant OAuth2 async library pattern. These classes handle the
exchange of Auth0 tokens for Duke Energy API tokens.

Architecture:
    Auth0Client (auth.py)           - Pure Auth0 OAuth2/OIDC client
            ↓
    AbstractDukeEnergyAuth          - Abstract base for DE authentication
            ↓
    DukeEnergyAuth                  - Concrete implementation using Auth0Client
            ↓
    DukeEnergy (dukeenergy.py)      - API client (no auth logic)
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import aiohttp
import yarl

from .auth0 import Auth0Client, decode_token, is_token_expired
from .exceptions import DukeEnergyAuthError, DukeEnergyTokenExpiredError

if TYPE_CHECKING:
    from aiohttp import ClientResponse

_LOGGER = logging.getLogger(__name__)

# Duke Energy API configuration
_BASE_URL = yarl.URL("https://api-v2.cma.duke-energy.app")
_AUTH_TOKEN_URL = _BASE_URL / "login" / "auth-token"

# Duke Energy API credentials (from mobile app)
_DE_CLIENT_ID = "HO2JKfv2dVuXhLHhleDr1s6fgVlPduGxVBO6GaS3dDjE7Kp8"
_DE_CLIENT_SECRET = "g4236o8ROFMD4JuVI4tsgLY7NiIEGXQgzzCnH9RiRrvFC6IN4KFg3A6dBmGIIuW6"  # noqa: S105


class AbstractDukeEnergyAuth(ABC):
    """
    Abstract base class for Duke Energy authentication.

    This follows the Home Assistant OAuth2 async library pattern, providing
    an abstract method for obtaining ID tokens and concrete implementations
    for exchanging those tokens for Duke Energy API access.

    Subclasses must implement async_get_id_token() to provide valid Auth0 ID
    tokens. The base class handles:
    - Exchanging ID tokens for Duke Energy API tokens (with caching)
    - Making authenticated requests to the Duke Energy API
    - Caching email and internal_user_id from token responses

    Example subclass for Home Assistant:
        class HADukeEnergyAuth(AbstractDukeEnergyAuth):
            def __init__(self, websession, oauth_session):
                super().__init__(websession)
                self._oauth_session = oauth_session

            async def async_get_id_token(self) -> str:
                # HA's OAuth session handles refresh automatically
                return await self._oauth_session.async_get_id_token()
    """

    def __init__(self, session: aiohttp.ClientSession, timeout: int = 10) -> None:
        """
        Initialize the auth provider.

        :param session: aiohttp client session for making requests.
        :param timeout: Request timeout in seconds.
        """
        self._session = session
        self._timeout = timeout
        self._de_access_token: str | None = None
        self._de_token_issued_at: datetime | None = None
        self._de_token_expires_in: int | None = None
        self._email: str | None = None
        self._internal_user_id: str | None = None

    @property
    def email(self) -> str | None:
        """
        Get the cached email address.

        This is populated when async_get_access_token() is called and the
        Duke Energy token exchange returns user information.
        """
        return self._email

    @property
    def internal_user_id(self) -> str | None:
        """
        Get the cached internal user ID.

        This is populated when async_get_access_token() is called and the
        Duke Energy token exchange returns user information.
        """
        return self._internal_user_id

    @abstractmethod
    async def async_get_id_token(self) -> str:
        """
        Return a valid Auth0 ID token.

        Subclasses must implement this method to provide a valid ID token.
        The implementation should handle token refresh if needed.

        :returns: A valid Auth0 ID token.
        :raises DukeEnergyTokenExpiredError: If token is expired and cannot be
            refreshed.
        """

    async def async_get_access_token(self) -> str:
        """
        Get a valid Duke Energy API access token.

        This exchanges the Auth0 ID token for a Duke Energy API token.
        The token is cached and only refreshed when needed.

        :returns: A valid Duke Energy API access token.
        :raises DukeEnergyAuthError: If token exchange fails.
        """
        # Only get id_token and exchange if DE token is expired
        if self._is_de_token_expired():
            id_token = await self.async_get_id_token()
            self._update_user_info_from_token(id_token)
            await self._exchange_for_duke_token(id_token)

        return self._de_access_token  # type: ignore[return-value]

    def _is_de_token_expired(self) -> bool:
        """
        Check if the Duke Energy API token is expired or missing.

        Uses a 60-second buffer before expiry to avoid edge cases.

        :returns: True if the token is expired or missing, False otherwise.
        """
        if not self._de_access_token:
            return True
        if not self._de_token_issued_at or not self._de_token_expires_in:
            return True

        # Check if token is expired (with 60 second buffer)
        expiry_time = self._de_token_issued_at.timestamp() + self._de_token_expires_in
        return datetime.now(timezone.utc).timestamp() >= (expiry_time - 60)

    def _update_user_info_from_token(self, id_token: str) -> None:
        """
        Update cached user info from the ID token.

        :param id_token: The Auth0 ID token to extract user info from.
        """
        try:
            payload = decode_token(id_token)
            if payload.get("email"):
                self._email = payload["email"]
            if payload.get("internal_identifier"):
                self._internal_user_id = payload["internal_identifier"]
        except Exception as err:
            _LOGGER.debug("Failed to extract user info from id_token: %s", err)

    async def _exchange_for_duke_token(self, id_token: str) -> None:
        """
        Exchange Auth0 id_token for Duke Energy API access token.

        Duke Energy's API requires their own token, which is obtained by
        exchanging the Auth0 id_token via their /login/auth-token endpoint.

        :param id_token: The Auth0 ID token to exchange.
        :raises DukeEnergyAuthError: If the exchange fails.
        """
        credentials = f"{_DE_CLIENT_ID}:{_DE_CLIENT_SECRET}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
            "platform": "iOS",
            "User-Agent": "Duke%20Energy/1241 CFNetwork/3860.300.31 Darwin/25.2.0",
        }

        _LOGGER.debug("Exchanging id_token for Duke Energy API token")

        async with self._session.post(
            str(_AUTH_TOKEN_URL),
            headers=headers,
            json={"idToken": id_token},
            timeout=self._timeout,
        ) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.error(
                    "Duke Energy token exchange failed: %s - %s",
                    response.status,
                    text,
                )
                raise DukeEnergyAuthError(
                    f"Duke Energy token exchange failed: {response.status} - {text}"
                )

            data = await response.json()
            self._de_access_token = data.get("access_token")
            # Use server's issued_at timestamp, fallback to current time
            issued_at = data.get("issued_at")
            if issued_at:
                self._de_token_issued_at = datetime.fromtimestamp(
                    issued_at, tz=timezone.utc
                )
            else:
                self._de_token_issued_at = datetime.now(timezone.utc)
            self._de_token_expires_in = data.get("expires_in", 1800)  # Default 30 min
            _LOGGER.debug("Duke Energy token exchange successful")

            # Update user info from response
            if data.get("internalUserID"):
                self._internal_user_id = data["internalUserID"]

    async def request(
        self,
        method: str,
        url: str | yarl.URL,
        **kwargs: Any,
    ) -> ClientResponse:
        """
        Make an authenticated request to the Duke Energy API.

        This method handles authentication automatically by getting a valid
        access token before making the request.

        :param method: HTTP method (GET, POST, etc.)
        :param url: URL to request.
        :param kwargs: Additional arguments passed to aiohttp request.
        :returns: The aiohttp ClientResponse.
        :raises DukeEnergyAuthError: If authentication fails.
        """
        access_token = await self.async_get_access_token()

        headers = kwargs.pop("headers", {})
        headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "platform": "iOS",
                "User-Agent": "Duke%20Energy/1250 CFNetwork/3860.300.31 Darwin/25.2.0",
            }
        )

        timeout = kwargs.pop("timeout", self._timeout)

        return await self._session.request(
            method,
            url,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )

    def invalidate_token(self) -> None:
        """
        Invalidate the cached Duke Energy access token.

        Call this when the token is known to be invalid (e.g., after a 401
        response) to force a re-exchange on the next request.
        """
        self._de_access_token = None
        self._de_token_issued_at = None
        self._de_token_expires_in = None


class DukeEnergyAuth(AbstractDukeEnergyAuth):
    """
    Concrete Duke Energy authentication using Auth0Client.

    This implementation uses an Auth0Client to manage OAuth tokens and
    implements the async_get_id_token() method with automatic token refresh.

    Example usage:
        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0_client)

            # Initial authentication
            auth_url, code_verifier = auth0_client.get_authorization_url()
            # ... user logs in and gets code ...
            await auth.authenticate_with_code(code, code_verifier)

            # Use with DukeEnergy client
            client = DukeEnergy(auth)
            accounts = await client.get_accounts()

            # Save tokens for later
            saved = auth.token
            # ... persist saved dict ...

            # Restore tokens in new session
            auth.restore_token(saved)
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth0_client: Auth0Client,
        timeout: int = 10,
        access_token: str | None = None,
        refresh_token: str | None = None,
        id_token: str | None = None,
    ) -> None:
        """
        Initialize with session and Auth0Client.

        :param session: aiohttp client session for making requests.
        :param auth0_client: Auth0Client for OAuth operations.
        :param timeout: Request timeout in seconds.
        :param access_token: Pre-obtained Auth0 access token.
        :param refresh_token: Pre-obtained Auth0 refresh token.
        :param id_token: Pre-obtained Auth0 ID token.
        """
        super().__init__(session, timeout)
        self._auth0_client = auth0_client
        self._access_token: str | None = access_token
        self._refresh_token: str | None = refresh_token
        self._id_token: str | None = id_token

        # If id_token provided, decode to populate email/internal_user_id
        if self._id_token:
            self._update_user_info_from_token(self._id_token)

    async def async_get_id_token(self) -> str:
        """
        Get a valid Auth0 ID token, refreshing if needed.

        :returns: A valid Auth0 ID token.
        :raises DukeEnergyAuthError: If not authenticated.
        :raises DukeEnergyTokenExpiredError: If token expired and refresh fails.
        """
        if not self._id_token:
            raise DukeEnergyAuthError(
                "Not authenticated. Call authenticate_with_code() first."
            )

        # Check if access token is expired (indicates id_token likely needs refresh too)
        if self._access_token and is_token_expired(self._access_token):
            _LOGGER.debug("Auth0 access token expired, attempting refresh")

            if not self._refresh_token:
                raise DukeEnergyTokenExpiredError(
                    "Access token expired and no refresh token available. "
                    "Re-authenticate via browser."
                )

            try:
                result = await self._auth0_client.refresh_token(self._refresh_token)
                self._access_token = result.get("access_token")
                self._refresh_token = result.get("refresh_token", self._refresh_token)
                self._id_token = result.get("id_token")
                _LOGGER.debug("Auth0 token refresh successful")

                # Invalidate Duke Energy token since id_token changed
                self.invalidate_token()

            except DukeEnergyAuthError as err:
                raise DukeEnergyTokenExpiredError(
                    f"Token refresh failed: {err}. Re-authenticate via browser."
                ) from err

        return self._id_token  # type: ignore[return-value]

    async def authenticate_with_code(
        self, code: str, code_verifier: str
    ) -> dict[str, Any]:
        """
        Complete authentication using an authorization code.

        Call this after the user has logged in via browser and you have
        captured the 'code' parameter from the cma-prod:// redirect URL.

        :param code: The authorization code from the redirect URL.
        :param code_verifier: The PKCE code verifier from get_authorization_url().
        :returns: Token response containing access_token, refresh_token, etc.
        :raises DukeEnergyAuthError: If authentication fails.
        """
        _LOGGER.debug("Exchanging authorization code for tokens")
        result = await self._auth0_client.exchange_code(code, code_verifier)

        self._access_token = result.get("access_token")
        self._refresh_token = result.get("refresh_token")
        self._id_token = result.get("id_token")

        # Update user info from id_token
        if self._id_token:
            self._update_user_info_from_token(self._id_token)

        # Exchange for Duke Energy API token
        if self._id_token:
            await self._exchange_for_duke_token(self._id_token)

        _LOGGER.debug("Authentication with code successful")
        return result

    @property
    def token(self) -> dict[str, Any] | None:
        """
        Get serializable token dict for persistence.

        :returns: Dictionary with tokens that can be saved and restored later.
        """
        if not self._access_token:
            return None

        return {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "id_token": self._id_token,
        }

    def restore_token(self, token_data: dict[str, Any]) -> None:
        """
        Restore tokens from persisted data.

        :param token_data: Dictionary with access_token, refresh_token, id_token.
        """
        self._access_token = token_data.get("access_token")
        self._refresh_token = token_data.get("refresh_token")
        self._id_token = token_data.get("id_token")

        # Update user info from id_token if available
        if self._id_token:
            self._update_user_info_from_token(self._id_token)

        # Clear Duke Energy token to force re-exchange
        self.invalidate_token()
