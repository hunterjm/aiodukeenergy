import re
from datetime import datetime, timedelta, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from aiodukeenergy import DukeEnergy


@pytest.fixture
def mock_auth_response():
    """Create a mock authentication response."""
    return {
        "refresh_token_expires_in": "86399",
        "issued_at": str(int(datetime.now(timezone.utc).timestamp())),
        "client_id": "client_id",
        "cdp_return_code": "0",
        "application_name": "application_name",
        "ccID": "test",
        "scope": "auth change_password",
        "pendingDelegation": "false",
        "refresh_token_issued_at": str(int(datetime.now(timezone.utc).timestamp())),
        "expires_in": "1199",
        "refresh_count": "0",
        "cdp_login_identity": "test",
        "onlineExperienceName": "SC_RESIDENTIAL",
        "cdp_message_text": "Success",
        "impersonating": "false",
        "access_token": "access_token",
        "refresh_token": "refresh_token",
        "internalUserID": "TEST",
        "loginEmailAddress": "TEST@EXAMPLE.COM",
        "pendingExperience": "false",
        "status": "approved",
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
                "serviceType": "serviceType",
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
    # Create time formats directly here, instead of using a global variable
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
            # Skip adding entry for 02 AM on first day to simulate missing data
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

    start = datetime.strptime("2024-01-01", "%Y-%m-%d")

    for day in range(31):
        current_date = start + timedelta(days=day)
        date_str = current_date.strftime("%m/%d/%Y")  # Format as MM/DD/YYYY

        # Day 3 (index 2) will have 0 usage to be detected as missing
        usage_value = "0" if day == 2 else str(day * 10)

        daily_data.append(
            {
                "date": date_str,
                "usage": usage_value,  # 10 kWh per day, 0 for day 3
                "temperatureAvg": 30,
            }
        )

    return daily_data


def setup_mocked_responses(
    mocked,
    mock_auth_response,
    mock_account_list_response,
    mock_account_details_response,
    mock_usage_data,
):
    """Set up the mocked responses for Duke Energy API."""
    # Mock authentication
    mocked.post(
        "https://api-v2.cma.duke-energy.app/login-services/auth-token",
        payload=mock_auth_response,
    )

    # Mock account list
    pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-list")
    mocked.get(pattern, payload=mock_account_list_response)

    # Mock account details
    pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-details-v2")
    mocked.get(pattern, payload=mock_account_details_response)

    # Mock usage graph
    pattern = re.compile(
        r"^https://api-v2\.cma\.duke-energy\.app/account/usage/graph.*meterSerialNumber="
    )
    mocked.get(pattern, payload={"usageArray": mock_usage_data})


@pytest.mark.asyncio
async def test_create_object():
    """Creating an object works as expected."""
    client = DukeEnergy("test", "passwd")
    assert client.timeout == 10
    assert client.username == "test"
    assert client.password == "passwd"  # noqa: S105
    assert client._created_session is True
    await client.close()


@pytest.mark.asyncio
async def test_create_object_passed_session():
    """Creating an object works as expected with a passed session."""
    session = aiohttp.ClientSession()
    client = DukeEnergy("test", "passwd", session)
    assert client.timeout == 10
    assert client.username == "test"
    assert client.password == "passwd"  # noqa: S105
    assert client._created_session is False
    await client.close()
    await session.close()


@pytest.mark.asyncio
async def test_get_accounts(
    mock_auth_response, mock_account_list_response, mock_account_details_response
):
    """Test getting account information."""
    with aioresponses() as mocked:
        client = DukeEnergy("test", "passwd")

        # Mock authentication
        mocked.post(
            "https://api-v2.cma.duke-energy.app/login-services/auth-token",
            payload=mock_auth_response,
        )

        # Mock account list
        pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-list")
        mocked.get(pattern, payload=mock_account_list_response)

        # Mock account details
        pattern = re.compile(
            r"^https://api-v2\.cma\.duke-energy\.app/account-details-v2"
        )
        mocked.get(pattern, payload=mock_account_details_response)

        accounts = await client.get_accounts()
        assert len(accounts) == 1
        assert "accountNumber" in accounts
        assert accounts["accountNumber"]["srcSysCd"] == "srcSysCd"

        await client.close()


@pytest.mark.asyncio
async def test_get_meters(
    mock_auth_response, mock_account_list_response, mock_account_details_response
):
    """Test getting meter information."""
    with aioresponses() as mocked:
        client = DukeEnergy("test", "passwd")

        # Set up mocked responses
        mocked.post(
            "https://api-v2.cma.duke-energy.app/login-services/auth-token",
            payload=mock_auth_response,
        )

        pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-list")
        mocked.get(pattern, payload=mock_account_list_response)

        pattern = re.compile(
            r"^https://api-v2\.cma\.duke-energy\.app/account-details-v2"
        )
        mocked.get(pattern, payload=mock_account_details_response)

        meters = await client.get_meters()
        assert len(meters) == 1
        assert "serialNum" in meters
        assert meters["serialNum"]["serviceType"] == "serviceType"

        await client.close()


@pytest.mark.asyncio
async def test_energy_usage(
    mock_auth_response,
    mock_account_list_response,
    mock_account_details_response,
    mock_usage_data,
):
    """Test getting energy usage."""
    with aioresponses() as mocked:
        client = DukeEnergy("test", "passwd")

        # Set up mocked responses
        setup_mocked_responses(
            mocked,
            mock_auth_response,
            mock_account_list_response,
            mock_account_details_response,
            mock_usage_data,
        )

        # Get meters
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
        assert result["missing"][0] == start  # First hour (12 AM) on first day
        assert result["missing"][1] == start + timedelta(hours=2)  # 02 AM on first day
        assert list(result["data"].values())[-1].get("temperature") == 30

        await client.close()


@pytest.mark.asyncio
async def test_daily_energy_usage(
    mock_auth_response,
    mock_account_list_response,
    mock_account_details_response,
    mock_daily_usage_data,
):
    """Test getting daily energy usage."""
    with aioresponses() as mocked:
        client = DukeEnergy("test", "passwd")

        # Mock auth and account responses
        mocked.post(
            "https://api-v2.cma.duke-energy.app/login-services/auth-token",
            payload=mock_auth_response,
        )

        pattern = re.compile(r"^https://api-v2\.cma\.duke-energy\.app/account-list")
        mocked.get(pattern, payload=mock_account_list_response)

        pattern = re.compile(
            r"^https://api-v2\.cma\.duke-energy\.app/account-details-v2"
        )
        mocked.get(pattern, payload=mock_account_details_response)

        # Mock usage graph using the fixture data
        pattern = re.compile(
            r"^https://api-v2\.cma\.duke-energy\.app/account/usage/graph.*meterSerialNumber="
        )
        mocked.get(pattern, payload={"usageArray": mock_daily_usage_data})

        # Get meters
        meters = await client.get_meters()
        serial_number = next(iter(meters.keys()))

        # Query for energy usage with DAILY interval
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
        missing_day = start + timedelta(days=2)  # Day 3 missing
        assert missing_day in result["missing"]

        # If we have data, check data points
        if result["data"]:
            # Check last day values
            last_day = start + timedelta(days=30)
            if last_day in result["data"]:
                assert result["data"][last_day]["energy"] == 300.0
                assert result["data"][last_day]["temperature"] == 30

        await client.close()
