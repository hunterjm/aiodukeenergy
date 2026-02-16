"""
Auth0 authentication client for Duke Energy.

This module handles OAuth2/OIDC authentication with Duke Energy's Auth0 tenant
using the mobile app flow. Authentication requires a browser-based login flow
since automated login is blocked by CAPTCHA.

Flow:
1. Call get_authorization_url() to get a URL for the user to open in a browser
2. User logs in via browser and gets redirected to cma-prod:// URL with code
3. Use a Chrome extension to capture the code from the cma-prod:// redirect
4. Call exchange_code() with the authorization code to get tokens
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import aiohttp
import jwt
import yarl

from .exceptions import DukeEnergyAuthError

_LOGGER = logging.getLogger(__name__)

# Auth0 configuration for Duke Energy
_AUTH0_DOMAIN = "login.duke-energy.com"
_AUTH0_BASE_URL = yarl.URL(f"https://{_AUTH0_DOMAIN}")
_AUTHORIZE_URL = _AUTH0_BASE_URL / "authorize"
_TOKEN_URL = _AUTH0_BASE_URL / "oauth" / "token"
_USERINFO_URL = _AUTH0_BASE_URL / "userinfo"

# Mobile app client configuration (required for Duke Energy API token exchange)
_CLIENT_ID = "PitoKqxMh8thrFF8rRlYGrAs3LbSD2dj"
# _REDIRECT_URI = "cma-prod://login.duke-energy.com/ios/com.dukeenergy.customerapp.release/callback"
_REDIRECT_URI = "https://login.duke-energy.com/ios/com.duke-energy.app/callback"
_AUTH0_CLIENT = base64.b64encode(
    json.dumps(
        {"env": {"iOS": "26.2", "swift": "6.x"}, "version": "2.13.0", "name": "Auth0.swift"}
    ).encode()
).decode()


def _generate_pkce_pair() -> tuple[str, str]:
    """
    Generate PKCE code_verifier and code_challenge (S256).

    Returns a tuple of (code_verifier, code_challenge).
    """
    # Generate code_verifier (43-128 chars, URL-safe)
    code_verifier = secrets.token_urlsafe(32)

    # Generate code_challenge = BASE64URL(SHA256(code_verifier))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


def _generate_state() -> str:
    """Generate a random state value (base64-encoded)."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _generate_nonce() -> str:
    """Generate a random nonce value (base64-encoded)."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode a JWT token without verification.

    :param token: The JWT token to decode.
    :returns: The decoded token payload.
    """
    return jwt.decode(token, options={"verify_signature": False})


def is_token_expired(token: str) -> bool:
    """
    Check if a JWT token is expired.

    :param token: The JWT token to check.
    :returns: True if the token is expired, False otherwise.
    """
    try:
        payload = decode_token(token)
        exp = payload.get("exp")
        if exp is None:
            return True
        return datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc)
    except (jwt.DecodeError, jwt.ExpiredSignatureError):
        return True


def extract_code_from_url(url: str) -> str | None:
    """
    Extract authorization code from redirect URL.

    :param url: The redirect URL containing the code parameter.
    :returns: The authorization code, or None if not found.
    """
    match = re.search(r"[?&]code=([^&]+)", url)
    return match.group(1) if match else None


class Auth0Client:
    """
    Auth0 authentication client for Duke Energy.

    This client handles the OAuth2/OIDC flow with Duke Energy's Auth0 tenant.
    It uses the mobile app configuration which is required to get an id_token
    that can be exchanged for a Duke Energy API access token.

    Example usage:
        client = Auth0Client(session)

        # Generate authorization URL for browser login
        auth_url, state, code_verifier = client.get_authorization_url()

        # User opens auth_url in browser, logs in, gets redirected to cma-prod://
        # Use Chrome extension to capture the code from the redirect URL

        # Exchange code for tokens
        tokens = await client.exchange_code(code, code_verifier)
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        timeout: int = 10,
    ) -> None:
        """
        Initialize the Auth0 client.

        :param session: The aiohttp session to use for requests.
        :param timeout: Request timeout in seconds.
        """
        self.session = session
        self.timeout = timeout
        self._code_verifier: str | None = None

    def get_authorization_url(self) -> tuple[str, str, str]:
        """
        Generate the authorization URL for browser-based OAuth flow.

        This method generates PKCE credentials and builds an authorization URL
        that can be opened in a browser. After the user logs in, they will be
        redirected to a cma-prod:// URL containing an authorization code.

        Use the Chrome extension from ./chrome-extension/ to capture
        the authorization code from the redirect.

        :returns: Tuple of (authorize_url, state, code_verifier).
                  Save the code_verifier - it's needed for token exchange.
        """
        self._code_verifier, code_challenge = _generate_pkce_pair()
        state = _generate_state()
        nonce = _generate_nonce()

        params = {
            "client_id": _CLIENT_ID,
            "scope": "openid profile email offline_access",
            "redirect_uri": _REDIRECT_URI,
            "response_type": "code",
            "response_mode": "query",
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "auth0Client": _AUTH0_CLIENT,
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        authorize_url = f"{_AUTHORIZE_URL}?{query}"

        return authorize_url, state, self._code_verifier

    async def exchange_code(
        self, code: str, code_verifier: str | None = None
    ) -> dict[str, Any]:
        """
        Exchange an authorization code for tokens.

        Use this after browser-based login to exchange the code from the
        redirect URL for access and refresh tokens.

        :param code: The authorization code from the redirect URL.
        :param code_verifier: The PKCE code_verifier from get_authorization_url().
                              If not provided, uses the internally stored verifier.
        :returns: Token response containing access_token, refresh_token, id_token, etc.
        :raises DukeEnergyAuthError: If the exchange fails.
        """
        if code_verifier:
            self._code_verifier = code_verifier

        if not self._code_verifier:
            raise DukeEnergyAuthError(
                "Code verifier not set. Call get_authorization_url() first "
                "or provide code_verifier parameter."
            )

        _LOGGER.debug("Exchanging authorization code for tokens")

        headers = {
            "accept-language": "en_US",
            "auth0-client": _AUTH0_CLIENT,
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Duke%20Energy/1241 CFNetwork/3860.300.31 Darwin/25.2.0",
        }

        response = await self.session.post(
            _TOKEN_URL,
            headers=headers,
            json={
                "grant_type": "authorization_code",
                "client_id": _CLIENT_ID,
                "code_verifier": self._code_verifier,
                "code": code,
                "redirect_uri": _REDIRECT_URI,
            },
            timeout=self.timeout,
        )

        if response.status != 200:
            text = await response.text()
            _LOGGER.error("Token exchange failed: %s", text)
            raise DukeEnergyAuthError(
                f"Token exchange failed: {response.status} - {text}"
            )

        result = await response.json()
        _LOGGER.debug("Token exchange successful")
        return result

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """
        Refresh the access token using a refresh token.

        :param refresh_token: The refresh token.
        :returns: Token response containing new access_token, refresh_token, etc.
        :raises DukeEnergyAuthError: If refresh fails.
        """
        _LOGGER.debug("Refreshing access token")

        headers = {
            "accept-language": "en_US",
            "auth0-client": _AUTH0_CLIENT,
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Duke%20Energy/1241 CFNetwork/3860.300.31 Darwin/25.2.0",
        }

        response = await self.session.post(
            _TOKEN_URL,
            headers=headers,
            json={
                "grant_type": "refresh_token",
                "client_id": _CLIENT_ID,
                "refresh_token": refresh_token,
            },
            timeout=self.timeout,
        )

        if response.status != 200:
            text = await response.text()
            _LOGGER.error("Token refresh failed: %s", text)
            raise DukeEnergyAuthError(
                f"Token refresh failed: {response.status} - {text}"
            )

        result = await response.json()
        _LOGGER.debug("Token refresh successful")
        return result

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """
        Get user information from Auth0.

        :param access_token: The access token.
        :returns: User info containing email, sub, etc.
        """
        response = await self.session.get(
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return await response.json()
