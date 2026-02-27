"""Tests for aiodukeenergy library."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import pytest
from aioresponses import aioresponses

from aiodukeenergy import (
    AbstractDukeEnergyAuth,
    Auth0Client,
    DukeEnergy,
    DukeEnergyAuth,
)


# Create a valid-looking JWT for testing (not cryptographically valid, but parseable)
def _create_test_jwt(exp_offset_seconds: int = 3600, **extra_claims: str) -> str:
    """Create a test JWT token with configurable expiration."""
    import base64
    import json

    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    exp = int(
        (datetime.now(timezone.utc) + timedelta(seconds=exp_offset_seconds)).timestamp()
    )
    payload_data = {
        "sub": "auth0|TEST",
        "email": "TEST@EXAMPLE.COM",
        "internal_identifier": "DUKE_TEST_USER",
        "exp": exp,
        **extra_claims,
    }
    payload = (
        base64.urlsafe_b64encode(json.dumps(payload_data).encode())
        .rstrip(b"=")
        .decode()
    )
    signature = base64.urlsafe_b64encode(b"fake_signature").rstrip(b"=").decode()
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def mock_auth0_token_response():
    """Create a mock Auth0 token response."""
    return {
        "access_token": _create_test_jwt(),
        "refresh_token": "refresh_token_value",
        "id_token": _create_test_jwt(de_auth="encrypted_auth_data"),
        "token_type": "Bearer",
        "expires_in": 86400,
    }


@pytest.fixture
def mock_duke_token_response():
    """Create a mock Duke Energy API token response."""
    return {
        "access_token": _create_test_jwt(),
        "internalUserID": "DUKE_TEST_USER",
        "email": "TEST@EXAMPLE.COM",
    }


@pytest.fixture
def mock_account_list_response():
    """Create a mock account list response."""
    return {
        "accounts": [
            {
                "accountNumber": "accountNumber",
                "primaryBpNumber": "primaryBpNumber",
                "serviceAddressParsed": {
                    "zipCode": "zipCode",
                    "addressLine1": "123 Test St",
                    "city": "Test City",
                    "state": "NC",
                },
                "srcSysCd": "srcSysCd",
                "srcAcctId": "srcAcctId",
                "srcAcctId2": "srcAcctId2",
            }
        ],
        "relatedBpNumber": "relatedBpNumber",
    }


@pytest.fixture
def mock_account_details_response():
    """Create a mock account details response."""
    return {
        "meterInfo": [
            {
                "serviceType": "ELECTRIC",
                "serialNum": "serialNum",
                "agreementActiveDate": "2000-01-01",
                "agreementEndDate": "2999-01-01",
                "meterCertificationDate": "2020-01-01",
            }
        ],
    }


@pytest.fixture
def mock_usage_data():
    """Create mock usage data for hourly interval."""
    hour_formats = [
        "12 AM",
        "01 AM",
        "02 AM",
        "03 AM",
        "04 AM",
        "05 AM",
        "06 AM",
        "07 AM",
        "08 AM",
        "09 AM",
        "10 AM",
        "11 AM",
        "12 PM",
        "01 PM",
        "02 PM",
        "03 PM",
        "04 PM",
        "05 PM",
        "06 PM",
        "07 PM",
        "08 PM",
        "09 PM",
        "10 PM",
        "11 PM",
    ]

    hourly_data = []
    for day in range(31):
        for hour in range(24):
            idx = day * 24 + hour
            # Skip 02 AM on first day to simulate missing data
            if day == 0 and hour == 2:
                continue
            hourly_data.append(
                {
                    "date": hour_formats[hour],
                    "usage": str(idx),
                    "temperatureAvg": 30,
                }
            )
    return hourly_data


@pytest.fixture
def mock_daily_usage_data():
    """Create mock usage data for daily interval."""
    daily_data = []
    start = datetime.strptime("2024-01-01", "%Y-%-m-%d")

    for day in range(31):
        current_date = start + timedelta(days=day)
        date_str = current_date.strftime("%-m/%d/%Y")
        # Day 3 (index 2) will have 0 usage (detected as missing)
        usage_value = "0" if day == 2 else str(day * 10)
        daily_data.append(
            {
                "date": date_str,
                "usage": usage_value,
                "temperatureAvg": 30,
            }
        )

    return daily_data


@pytest.fixture
def mock_duplicate_hours_data():
    """Create mock usage data with duplicate hours (simulating DST fall back)."""
    hour_formats = [
        "12 AM",
        "01 AM",
        "02 AM",
        "03 AM",
        "04 AM",
        "05 AM",
        "06 AM",
        "07 AM",
        "08 AM",
        "09 AM",
        "10 AM",
        "11 AM",
        "12 PM",
        "01 PM",
        "02 PM",
        "03 PM",
        "04 PM",
        "05 PM",
        "06 PM",
        "07 PM",
        "08 PM",
        "09 PM",
        "10 PM",
        "11 PM",
    ]

    hourly_data = []
    for day in range(2):  # Just use 2 days for this test
        for hour in range(24):
            idx = day * 24 + hour

            # Add the regular entry
            hourly_data.append(
                {"date": hour_formats[hour], "usage": str(idx), "temperatureAvg": 30}
            )

            # For day 1, duplicate the 1 AM hour to simulate DST fall back
            if day == 1 and hour == 1:
                hourly_data.append(
                    {
                        "date": hour_formats[hour],
                        "usage": str(900),  # Special value for the duplicate hour
                        "temperatureAvg": 25,
                    }
                )

    return hourly_data


def setup_api_mocks(mocked, account_list, account_details, usage_data=None):
    """Set up the mocked responses for Duke Energy API."""
    # Mock account list
    pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-list")
    mocked.get(pattern, payload=account_list, repeat=True)

    # Mock account details
    pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-details-v2")
    mocked.get(pattern, payload=account_details, repeat=True)

    # Mock usage graph
    if usage_data is not None:
        pattern = re.compile(
            r"^https://api-v2\.cma\.duke-energy\.app/account/usage/graph"
        )
        mocked.post(pattern, payload={"usageArray": usage_data}, repeat=True)


def setup_auth_mocks(mocked, mock_duke_token_response, mock_auth0_token_response=None):
    """Set up authentication mocks."""
    # Mock Duke Energy API token exchange
    mocked.post(
        "https://api-v2.cma.duke-energy.app/login/auth-token",
        payload=mock_duke_token_response,
        repeat=True,
    )

    # Mock Auth0 token endpoint
    if mock_auth0_token_response:
        mocked.post(
            "https://login.duke-energy.com/oauth/token",
            payload=mock_auth0_token_response,
            repeat=True,
        )


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    return aiohttp.ClientSession()


class MockAuth(AbstractDukeEnergyAuth):
    """Mock auth implementation for testing DukeEnergy client."""

    def __init__(self, session, email="TEST@EXAMPLE.COM", user_id="DUKE_TEST_USER"):
        super().__init__(session)
        self._email = email
        self._internal_user_id = user_id
        self._mock_responses = {}

    async def async_get_id_token(self) -> str:
        return _create_test_jwt()

    def set_mock_response(self, url_pattern: str, response: dict[str, Any]) -> None:
        """Set a mock response for a URL pattern."""
        self._mock_responses[url_pattern] = response


class TestClientCreation:
    """Tests for DukeEnergy client creation."""

    @pytest.mark.asyncio
    async def test_create_client_with_mock_auth(self):
        """Creating a client with mock auth works as expected."""
        async with aiohttp.ClientSession() as session:
            auth = MockAuth(session)
            client = DukeEnergy(auth)
            assert client.email == "TEST@EXAMPLE.COM"
            assert client.internal_user_id == "DUKE_TEST_USER"

    @pytest.mark.asyncio
    async def test_create_duke_energy_auth_with_tokens(self):
        """Creating DukeEnergyAuth with pre-provided tokens works."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_refresh = "refresh_token_value"
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token=test_refresh,
                id_token=test_id_token,
            )
            # Email should be populated from id_token
            assert auth.email == "TEST@EXAMPLE.COM"
            assert auth.internal_user_id == "DUKE_TEST_USER"

    @pytest.mark.asyncio
    async def test_duke_energy_auth_token_property(self):
        """Test that token property returns serializable dict."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_refresh = "refresh_token_value"
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token=test_refresh,
                id_token=test_id_token,
            )
            token_dict = auth.token
            assert token_dict is not None
            assert token_dict["access_token"] == test_token
            assert token_dict["refresh_token"] == test_refresh
            assert token_dict["id_token"] == test_id_token


class TestAuthorizationURL:
    """Tests for authorization URL generation."""

    @pytest.mark.asyncio
    async def test_get_authorization_url(self):
        """Test generating authorization URL."""
        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)

            auth_url, state, code_verifier = auth0_client.get_authorization_url()

            # Check URL structure
            assert auth_url.startswith("https://login.duke-energy.com/authorize")
            assert "client_id=" in auth_url
            assert "redirect_uri=" in auth_url
            assert "response_type=code" in auth_url
            assert "code_challenge=" in auth_url
            assert "code_challenge_method=S256" in auth_url
            assert "state=" in auth_url

            # State and code_verifier should be non-empty
            assert len(state) > 0
            assert len(code_verifier) > 0


class TestCodeExchange:
    """Tests for authorization code exchange."""

    @pytest.mark.asyncio
    async def test_authenticate_with_code(
        self,
        mock_auth0_token_response,
        mock_duke_token_response,
    ):
        """Test exchanging authorization code for tokens."""
        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)

            # Generate auth URL first (to get code_verifier)
            auth_url, state, code_verifier = auth0_client.get_authorization_url()

            auth = DukeEnergyAuth(session, auth0_client)

            with aioresponses() as mocked:
                # Mock Auth0 token endpoint
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    payload=mock_auth0_token_response,
                )

                # Mock Duke Energy API token exchange
                mocked.post(
                    "https://api-v2.cma.duke-energy.app/login/auth-token",
                    payload=mock_duke_token_response,
                )

                # Exchange code
                result = await auth.authenticate_with_code(
                    "test_auth_code", code_verifier
                )

                assert "access_token" in result
                assert auth.token is not None
                assert auth.internal_user_id == "DUKE_TEST_USER"

    @pytest.mark.asyncio
    async def test_get_id_token_without_authentication(self):
        """Test that async_get_id_token fails without authentication."""
        from aiodukeenergy import DukeEnergyAuthError

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0_client)

            with pytest.raises(DukeEnergyAuthError, match="Not authenticated"):
                await auth.async_get_id_token()


class TestTokenRefresh:
    """Tests for token refresh functionality."""

    @pytest.mark.asyncio
    async def test_refresh_expired_token(
        self,
        mock_auth0_token_response,
        mock_duke_token_response,
        mock_account_list_response,
    ):
        """Test that expired tokens are automatically refreshed."""
        # Create an expired token
        expired_token = _create_test_jwt(exp_offset_seconds=-3600)
        expired_id_token = _create_test_jwt(exp_offset_seconds=-3600)
        fresh_token = _create_test_jwt(exp_offset_seconds=3600)
        fresh_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=expired_token,
                refresh_token="refresh_token",  # noqa: S106
                id_token=expired_id_token,
            )

            with aioresponses() as mocked:
                # Mock token refresh
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    payload={
                        **mock_auth0_token_response,
                        "access_token": fresh_token,
                        "id_token": fresh_id_token,
                    },
                )

                # Mock Duke Energy API token exchange (for the refreshed token)
                setup_auth_mocks(mocked, mock_duke_token_response)

                # Mock account list endpoint
                setup_api_mocks(mocked, mock_account_list_response, {"meterInfo": []})

                # Create client and trigger API call (which triggers token refresh)
                client = DukeEnergy(auth)
                await client.get_accounts()

                # Token should now be refreshed
                token = auth.token
                assert token is not None
                assert token["access_token"] == fresh_token


class TestAccountAPI:
    """Tests for account-related API calls."""

    @pytest.mark.asyncio
    async def test_get_accounts(
        self,
        mock_duke_token_response,
        mock_account_list_response,
        mock_account_details_response,
    ):
        """Test getting account information."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token="refresh",  # noqa: S106
                id_token=test_id_token,
            )

            with aioresponses() as mocked:
                setup_auth_mocks(mocked, mock_duke_token_response)
                setup_api_mocks(
                    mocked,
                    mock_account_list_response,
                    mock_account_details_response,
                )

                client = DukeEnergy(auth)
                accounts = await client.get_accounts()

                assert len(accounts) == 1
                assert "accountNumber" in accounts
                assert accounts["accountNumber"]["srcSysCd"] == "srcSysCd"

    @pytest.mark.asyncio
    async def test_get_meters(
        self,
        mock_duke_token_response,
        mock_account_list_response,
        mock_account_details_response,
    ):
        """Test getting meter information."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token="refresh",  # noqa: S106
                id_token=test_id_token,
            )

            with aioresponses() as mocked:
                setup_auth_mocks(mocked, mock_duke_token_response)
                setup_api_mocks(
                    mocked,
                    mock_account_list_response,
                    mock_account_details_response,
                )

                client = DukeEnergy(auth)
                meters = await client.get_meters()

                assert len(meters) == 1
                assert "serialNum" in meters
                assert meters["serialNum"]["serviceType"] == "ELECTRIC"


class TestUsageAPI:
    """Tests for energy usage API calls."""

    @pytest.mark.asyncio
    async def test_hourly_energy_usage(
        self,
        mock_duke_token_response,
        mock_account_list_response,
        mock_account_details_response,
        mock_usage_data,
    ):
        """Test getting hourly energy usage."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token="refresh",  # noqa: S106
                id_token=test_id_token,
            )

            with aioresponses() as mocked:
                setup_auth_mocks(mocked, mock_duke_token_response)
                setup_api_mocks(
                    mocked,
                    mock_account_list_response,
                    mock_account_details_response,
                    mock_usage_data,
                )

                client = DukeEnergy(auth)

                # Get meters first
                meters = await client.get_meters()
                serial_number = next(iter(meters.keys()))

                # Query for energy usage
                start = datetime.strptime("2024-01-01", "%Y-%m-%d")
                end = datetime.strptime("2024-01-31", "%Y-%m-%d")
                result = await client.get_energy_usage(
                    serial_number,
                    "HOURLY",
                    "DAY",
                    start,
                    end,
                )

                # Check results
                assert len(result["data"]) == (31 * 24) - 2
                assert len(result["missing"]) == 2
                assert result["missing"][0] == start  # First hour on first day
                assert result["missing"][1] == start + timedelta(hours=2)  # 02 AM
                assert list(result["data"].values())[-1].get("temperature") == 30

    @pytest.mark.asyncio
    async def test_daily_energy_usage(
        self,
        mock_duke_token_response,
        mock_account_list_response,
        mock_account_details_response,
        mock_daily_usage_data,
    ):
        """Test getting daily energy usage."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token="refresh",  # noqa: S106
                id_token=test_id_token,
            )

            with aioresponses() as mocked:
                setup_auth_mocks(mocked, mock_duke_token_response)
                setup_api_mocks(
                    mocked,
                    mock_account_list_response,
                    mock_account_details_response,
                    mock_daily_usage_data,
                )

                client = DukeEnergy(auth)

                # Get meters first
                meters = await client.get_meters()
                serial_number = next(iter(meters.keys()))

                # Query for energy usage
                start = datetime.strptime("2024-01-01", "%Y-%m-%d")
                end = datetime.strptime("2024-01-31", "%Y-%m-%d")
                result = await client.get_energy_usage(
                    serial_number,
                    "DAILY",
                    "BILLINGCYCLE",
                    start,
                    end,
                )

                # Check results
                assert len(result["data"]) > 0, "No data was processed"
                assert len(result["missing"]) > 0, "No missing days detected"

                # Day 3 should be missing (0 usage)
                missing_day = start + timedelta(days=2)
                assert missing_day in result["missing"]

    @pytest.mark.asyncio
    async def test_energy_usage_duplicate_hours(
        self,
        mock_duke_token_response,
        mock_account_list_response,
        mock_account_details_response,
        mock_duplicate_hours_data,
    ):
        """Test energy usage handling duplicate hours (like during DST changes)."""
        test_token = _create_test_jwt(exp_offset_seconds=3600)
        test_id_token = _create_test_jwt(exp_offset_seconds=3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=test_token,
                refresh_token="refresh",  # noqa: S106
                id_token=test_id_token,
            )

            with aioresponses() as mocked:
                setup_auth_mocks(mocked, mock_duke_token_response)
                setup_api_mocks(
                    mocked,
                    mock_account_list_response,
                    mock_account_details_response,
                    mock_duplicate_hours_data,
                )

                client = DukeEnergy(auth)

                # Get meters first
                meters = await client.get_meters()
                serial_number = next(iter(meters.keys()))

                # Query for energy usage - use a 2-day period
                start = datetime.strptime("2024-01-01", "%Y-%m-%d")
                end = datetime.strptime("2024-01-02", "%Y-%m-%d")
                result = await client.get_energy_usage(
                    serial_number,
                    "HOURLY",
                    "DAY",
                    start,
                    end,
                )

                # We should have 48 hours of data (2 days), minus 1 for the duplicate
                expected_data_count = (2 * 24) - 1
                assert len(result["data"]) == expected_data_count, (
                    f"Expected {expected_data_count} data points, "
                    f"got {len(result['data'])}"
                )

                # Verify all timestamps are sequential (no duplicates)
                timestamps = sorted(result["data"].keys())
                for i in range(1, len(timestamps)):
                    time_diff = timestamps[i] - timestamps[i - 1]
                    assert time_diff == timedelta(
                        hours=1
                    ), f"Expected 1 hour difference, got {time_diff}"

                # The 1 AM on day 2 should have the first value, not the duplicate
                day2_1am = start + timedelta(days=1, hours=1)
                if day2_1am in result["data"]:
                    energy_value = result["data"][day2_1am]["energy"]
                    assert (
                        energy_value != 900.0
                    ), "Should not have the duplicate hour value (900.0)"


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_get_id_token_without_authentication(self):
        """Test that async_get_id_token fails without authentication."""
        from aiodukeenergy import DukeEnergyAuthError

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0_client)

            with pytest.raises(DukeEnergyAuthError, match="Not authenticated"):
                await auth.async_get_id_token()

    @pytest.mark.asyncio
    async def test_token_refresh_with_expired_token_no_refresh(self):
        """Test token refresh with expired token and no refresh token."""
        from aiodukeenergy import DukeEnergyTokenExpiredError

        expired_token = _create_test_jwt(exp_offset_seconds=-3600)
        expired_id_token = _create_test_jwt(exp_offset_seconds=-3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=expired_token,
                id_token=expired_id_token,
                # No refresh token provided
            )

            with pytest.raises(DukeEnergyTokenExpiredError):
                await auth.async_get_id_token()

    @pytest.mark.asyncio
    async def test_auth0_token_exchange_failure(self):
        """Test Auth0 token exchange returns error on failure."""
        from aiodukeenergy import DukeEnergyAuthError

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0_client)

            with aioresponses() as mocked:
                # Mock Auth0 token endpoint with error
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    status=400,
                    payload={"error": "invalid_grant"},
                )

                with pytest.raises(DukeEnergyAuthError, match="Token exchange failed"):
                    await auth.authenticate_with_code("bad_code", "verifier")

    @pytest.mark.asyncio
    async def test_duke_energy_token_exchange_failure(self, mock_auth0_token_response):
        """Test Duke Energy token exchange returns error on failure."""
        from aiodukeenergy import DukeEnergyAuthError

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0_client)

            with aioresponses() as mocked:
                # Mock Auth0 token endpoint success
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    payload=mock_auth0_token_response,
                )
                # Mock Duke Energy API token exchange with error
                mocked.post(
                    "https://api-v2.cma.duke-energy.app/login/auth-token",
                    status=401,
                    payload={"error": "unauthorized"},
                )

                with pytest.raises(
                    DukeEnergyAuthError, match="Duke Energy token exchange failed"
                ):
                    await auth.authenticate_with_code("test_code", "verifier")

    @pytest.mark.asyncio
    async def test_auth0_token_refresh_failure(self):
        """Test Auth0 token refresh returns error on failure."""
        from aiodukeenergy import DukeEnergyTokenExpiredError

        expired_token = _create_test_jwt(exp_offset_seconds=-3600)
        expired_id_token = _create_test_jwt(exp_offset_seconds=-3600)

        async with aiohttp.ClientSession() as session:
            auth0_client = Auth0Client(session)
            auth = DukeEnergyAuth(
                session,
                auth0_client,
                access_token=expired_token,
                id_token=expired_id_token,
                refresh_token="refresh_token",  # noqa: S106
            )

            with aioresponses() as mocked:
                # Mock Auth0 refresh endpoint with error
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    status=400,
                    payload={"error": "invalid_grant"},
                )

                with pytest.raises(DukeEnergyTokenExpiredError, match="Token refresh"):
                    await auth.async_get_id_token()


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_extract_code_from_url_valid(self):
        """Test extracting authorization code from valid redirect URL."""
        from aiodukeenergy.auth0 import extract_code_from_url

        url = "https://login.duke-energy.com/ios/com.duke-energy.app/callback?code=abc123&state=xyz"
        code = extract_code_from_url(url)
        assert code == "abc123"

    def test_extract_code_from_url_no_code(self):
        """Test extracting authorization code when not present."""
        from aiodukeenergy.auth0 import extract_code_from_url

        url = "https://login.duke-energy.com/ios/com.duke-energy.app/callback?state=xyz"
        code = extract_code_from_url(url)
        assert code is None

    def test_extract_code_from_url_with_ampersand(self):
        """Test extracting authorization code with trailing parameters."""
        from aiodukeenergy.auth0 import extract_code_from_url

        url = "https://login.duke-energy.com/ios/com.duke-energy.app/callback?code=test_code_123&state=abc&other=param"
        code = extract_code_from_url(url)
        assert code == "test_code_123"

    def test_is_token_expired_valid_token(self):
        """Test is_token_expired with a valid non-expired token."""
        from aiodukeenergy.auth0 import is_token_expired

        token = _create_test_jwt(exp_offset_seconds=3600)  # 1 hour in future
        assert is_token_expired(token) is False

    def test_is_token_expired_expired_token(self):
        """Test is_token_expired with an expired token."""
        from aiodukeenergy.auth0 import is_token_expired

        token = _create_test_jwt(exp_offset_seconds=-3600)  # 1 hour ago
        assert is_token_expired(token) is True

    def test_is_token_expired_invalid_token(self):
        """Test is_token_expired with an invalid token."""
        from aiodukeenergy.auth0 import is_token_expired

        assert is_token_expired("invalid.token") is True
        assert is_token_expired("") is True

    def test_is_token_expired_no_exp_claim(self):
        """Test is_token_expired with token missing exp claim."""
        import jwt as pyjwt

        from aiodukeenergy.auth0 import is_token_expired

        # Create token without exp claim
        payload = {"email": "test@example.com"}
        token = pyjwt.encode(payload, "secret", algorithm="HS256")
        assert is_token_expired(token) is True

    def test_decode_token(self):
        """Test decode_token returns payload."""
        from aiodukeenergy.auth0 import decode_token

        token = _create_test_jwt()
        payload = decode_token(token)
        assert payload["email"] == "TEST@EXAMPLE.COM"
        assert payload["internal_identifier"] == "DUKE_TEST_USER"


class TestAuth0Client:
    """Tests for Auth0Client class."""

    @pytest.mark.asyncio
    async def test_exchange_code_without_verifier(self):
        """Test exchange_code raises error when verifier not set."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuthError

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            # Don't call get_authorization_url first, so no verifier is set
            with pytest.raises(DukeEnergyAuthError, match="Code verifier not set"):
                await auth0.exchange_code("test_code")

    @pytest.mark.asyncio
    async def test_get_user_info(self):
        """Test getting user info from Auth0."""
        from aiodukeenergy import Auth0Client

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)

            with aioresponses() as mocked:
                mocked.get(
                    "https://login.duke-energy.com/userinfo",
                    payload={"email": "test@example.com", "sub": "user123"},
                )

                user_info = await auth0.get_user_info("test_access_token")
                assert user_info["email"] == "test@example.com"
                assert user_info["sub"] == "user123"


class TestDukeEnergyAuthTokenManagement:
    """Tests for DukeEnergyAuth token management."""

    @pytest.mark.asyncio
    async def test_token_property_returns_none_when_not_authenticated(self):
        """Test token property returns None when not authenticated."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuth

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0)
            assert auth.token is None

    @pytest.mark.asyncio
    async def test_restore_token(self):
        """Test restore_token restores tokens and user info."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuth

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0)

            # Create token data with valid JWT for user info extraction
            id_token = _create_test_jwt()
            token_data = {
                "access_token": "restored_access",
                "refresh_token": "restored_refresh",
                "id_token": id_token,
            }

            auth.restore_token(token_data)

            assert auth.token is not None
            assert auth.token["access_token"] == "restored_access"  # noqa: S105
            assert auth.token["refresh_token"] == "restored_refresh"  # noqa: S105
            assert auth.email == "TEST@EXAMPLE.COM"
            assert auth.internal_user_id == "DUKE_TEST_USER"

    @pytest.mark.asyncio
    async def test_restore_token_with_invalid_id_token(self):
        """Test restore_token handles invalid id_token gracefully."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuth

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0)

            # Restore with invalid id_token - should not raise
            token_data = {
                "access_token": "restored_access",
                "refresh_token": "restored_refresh",
                "id_token": "invalid.jwt.token",
            }

            # Should not raise, just log debug message
            auth.restore_token(token_data)
            assert auth.token is not None

    @pytest.mark.asyncio
    async def test_duke_token_expired_without_expiry_info(self):
        """Test DE token is considered expired when no expiry info."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuth

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0)

            # Set only the DE access token without issued_at/expires_in
            auth._de_access_token = "some_token"  # noqa: S105
            auth._de_token_issued_at = None
            auth._de_token_expires_in = None

            # Token should be considered expired
            assert auth._is_de_token_expired() is True

    @pytest.mark.asyncio
    async def test_duke_token_with_server_issued_at(self, mock_auth0_token_response):
        """Test Duke token exchange uses server's issued_at timestamp."""
        from aiodukeenergy import Auth0Client, DukeEnergyAuth

        async with aiohttp.ClientSession() as session:
            auth0 = Auth0Client(session)
            auth = DukeEnergyAuth(session, auth0)

            server_issued_at = 1700000000  # Fixed timestamp

            with aioresponses() as mocked:
                # Mock Auth0 token endpoint
                mocked.post(
                    "https://login.duke-energy.com/oauth/token",
                    payload=mock_auth0_token_response,
                )
                # Mock Duke Energy API token exchange with server-provided issued_at
                mocked.post(
                    "https://api-v2.cma.duke-energy.app/login/auth-token",
                    payload={
                        "access_token": "de_token",
                        "expires_in": 1800,
                        "issued_at": server_issued_at,
                    },
                )

                await auth.authenticate_with_code("test_code", "verifier")

                # Verify server timestamp was used
                assert auth._de_token_issued_at is not None
                assert auth._de_token_issued_at.timestamp() == server_issued_at


class TestImports:
    """Tests for module imports and exports."""

    def test_package_exports(self):
        """Test that the package exports the expected symbols."""
        from aiodukeenergy import (
            AbstractDukeEnergyAuth,
            Auth0Client,
            DukeEnergy,
            DukeEnergyAuth,
            DukeEnergyAuthError,
            DukeEnergyError,
            DukeEnergyTokenExpiredError,
        )

        assert AbstractDukeEnergyAuth is not None
        assert Auth0Client is not None
        assert DukeEnergy is not None
        assert DukeEnergyAuth is not None
        assert DukeEnergyError is not None
        assert DukeEnergyAuthError is not None
        assert DukeEnergyTokenExpiredError is not None

    def test_duke_energy_auth_is_subclass_of_abstract(self):
        """Test that DukeEnergyAuth is a subclass of AbstractDukeEnergyAuth."""
        from aiodukeenergy import AbstractDukeEnergyAuth, DukeEnergyAuth

        assert issubclass(DukeEnergyAuth, AbstractDukeEnergyAuth)

    def test_version_available(self):
        """Test that version is available."""
        from aiodukeenergy import __version__

        assert __version__ is not None
        assert isinstance(__version__, str)
