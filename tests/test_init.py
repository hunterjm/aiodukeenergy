import re
from datetime import datetime, timezone

import aiohttp
import pytest
from aioresponses import aioresponses

from aiodukeenergy import DukeEnergy


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
async def test_simple_requests():
    """Mocked tests for requests."""
    with aioresponses() as mocked:
        client = DukeEnergy("test", "passwd")
        assert client.timeout == 10
        assert client.username == "test"
        assert client.password == "passwd"  # noqa: S105
        assert client._created_session is True
        mocked.post(
            "https://prod.apigee.duke-energy.app/gep/v2/auth-oauth2/token",
            payload={
                "refresh_token_expires_in": "86399",
                "issued_at": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
                "client_id": "client_id",
                "cdp_return_code": "0",
                "application_name": "application_name",
                "ccID": "test",
                "scope": "auth change_password",
                "pendingDelegation": "false",
                "refresh_token_issued_at": str(
                    int(datetime.now(timezone.utc).timestamp() * 1000)
                ),
                "expires_in": "1199",
                "refresh_count": "0",
                "email": "TEST@EXAMPLE.COM",
                "cdp_login_identity": "test",
                "onlineExperienceName": "SC_RESIDENTIAL",
                "cdp_message_text": "Success",
                "impersonating": "false",
                "access_token": "access_token",
                "refresh_token": "refresh_token",
                "cdp_internal_user_id": "TEST",
                "pendingExperience": "false",
                "status": "approved",
            },
        )
        pattern = re.compile(
            r"^https://prod.apigee\.duke-energy\.app/gep/v2/auth-services/account-list"
        )
        mocked.get(
            pattern,
            payload={
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
            },
        )
        pattern = re.compile(
            r"^https://prod.apigee\.duke-energy\.app/gep/v2/auth-services/account-details-v2"
        )
        mocked.get(
            pattern,
            payload={
                "meterInfo": [
                    {
                        "serviceType": "serviceType",
                        "serialNum": "serialNum",
                        "agreementActiveDate": "2000-01-01",
                        "agreementEndDate": "2999-01-01",
                        "meterCertificationDate": "2020-01-01",
                    }
                ],
            },
        )
        meters = await client.get_meters()
        serial_number = next(iter(meters.keys()))
        pattern = re.compile(
            r"^https://prod.apigee\.duke-energy\.app/gep/v2/auth-services/energy-usage-graph.*meterSerialNumber="
        )
        mocked.get(
            pattern,
            payload={
                "Series1": list(range(31 * 24)),
                "Series3": list(range(31)),
                "MissingDataError": "",
            },
        )
        result = await client.get_energy_usage(
            serial_number,
            "HOURLY",
            "DAY",
            datetime.strptime("2024-01-01", "%Y-%m-%d"),
            datetime.strptime("2024-01-31", "%Y-%m-%d"),
        )
        # 0 range for energy gets put into missing
        assert len(result["data"]) == (31 * 24) - 1
        assert len(result["missing"]) == 1
        assert list(result["data"].values())[-1].get("temperature") == 30
        await client.close()
