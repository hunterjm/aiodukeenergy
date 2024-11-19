from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import aiohttp
import yarl

_BASE_URL = yarl.URL("https://prod.apigee.duke-energy.app/gep/v2")
_SERVICES_URL = _BASE_URL.joinpath("auth-services")

# Client ID and Secret are from the Android app
_TOKEN_URL = _BASE_URL.joinpath("auth-oauth2", "token")
_CLIENT_ID = "g3c4MJTD3lciM2UoJA8CZkBIM87ckAkRXxeK5HpuzL5iVN28"
_CLIENT_SECRET = "w4O5CxynH0M4zzRhCOaFyKplHV50GnQYyR2rxDbMBsUQ9qYlVOGRYuHg7hiXKtje"  # noqa: S105
_TOKEN_AUTH = base64.b64encode(f"{_CLIENT_ID}:{_CLIENT_SECRET}".encode()).decode()

_DATE_FORMAT = "%m/%d/%Y"

_LOGGER = logging.getLogger(__name__)


class DukeEnergy:
    """Duke Energy API client."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        timeout: int = 10,
    ) -> None:
        """Initialize the Duke Energy API client."""
        self.username = username
        self.password = password
        self.session = session or aiohttp.ClientSession()
        self._created_session = not session
        self.timeout = timeout
        self._auth: dict[str, Any] | None = None
        self._accounts: dict[str, Any] | None = None
        self._meters: dict[str, Any] | None = None

    @property
    def internal_user_id(self) -> str | None:
        """Get the internal user ID from auth response."""
        return self._auth.get("cdp_internal_user_id") if self._auth else None

    @property
    def email(self) -> str | None:
        """Get the email from auth response."""
        return self._auth.get("email") if self._auth else None

    async def close(self) -> None:
        """Close the SolarEdge API client."""
        if self._created_session:
            await self.session.close()

    async def authenticate(self) -> dict[str, Any]:
        """Authenticate with Duke Energy."""
        _LOGGER.debug("Fetching Auth Token")
        response = await self.session.post(
            _TOKEN_URL,
            headers={"Authorization": f"Basic {_TOKEN_AUTH}"},
            data={
                "grant_type": "password",
                "username": self.username,
                "password": self.password,
            },
            timeout=self.timeout,
        )
        _LOGGER.debug("Response from %s: %s", _TOKEN_URL, response.status)
        response.raise_for_status()
        result = await response.json()
        self._auth = result
        return result

    async def get_accounts(self, fresh: bool = False) -> dict[str, dict[str, Any]]:
        """
        Get account details from Duke Energy.

        :param fresh: Whether to fetch fresh data.
        """
        if self._accounts and not fresh:
            return self._accounts

        if not self.email or not self.internal_user_id:
            await self._validate_auth()

        account_list = await self._get_json(
            _SERVICES_URL.joinpath("account-list"),
            {
                "email": self.email,
                "internalUserID": self.internal_user_id,
                "fetchFreshData": "true",
            },
        )

        accounts = {}
        for account in account_list["accounts"]:
            details = await self._get_json(
                _SERVICES_URL.joinpath("account-details-v2"),
                {
                    "email": self.email,
                    "srcSysCd": account["srcSysCd"],
                    "srcAcctId": account["srcAcctId"],
                    "primaryBpNumber": account["primaryBpNumber"],
                    "relatedBpNumber": account_list["relatedBpNumber"],
                },
            )
            accounts[account["accountNumber"]] = {
                **account,
                "details": details,
            }

        self._accounts = accounts
        return self._accounts

    async def get_meters(self, fresh: bool = False) -> dict[str, dict[str, Any]]:
        """
        Get meter details from Duke Energy.

        :param fresh: Whether to fetch fresh data.
        """
        if self._meters and not fresh:
            return self._meters

        if not self._accounts:
            await self.get_accounts(fresh)

        meters = {}
        for account in self._accounts.values() if self._accounts else []:
            for meter in account["details"]["meterInfo"]:
                # set meter info and add account without details
                meters[meter["serialNum"]] = {
                    **meter,
                    "account": {k: v for k, v in account.items() if k != "details"},
                }

        self._meters = meters
        return self._meters

    async def get_energy_usage(
        self,
        serial_number: str,
        interval: Literal["HOURLY", "DAILY"],
        period: Literal["DAY", "WEEK", "BILLINGCYCLE"],
        start_date: datetime,
        end_date: datetime,
        include_temperature: bool = True,
    ) -> dict[str, Any]:
        """
        Get energy usage from Duke Energy.

        :param serial_number: The serial number of the meter.
        :param interval: The interval.
        :param period: The period.
        :param start_date: The start date.
        :param end_date: The end date.
        :param include_temperature: Whether to include temperature.
        """
        if not self._meters:
            await self.get_meters()

        meter = self._meters.get(serial_number) if self._meters else None

        if meter is None:
            raise ValueError(f"Meter {serial_number} not found")

        result = await self._get_json(
            _SERVICES_URL.joinpath("energy-usage-graph"),
            {
                "srcSysCd": meter["account"]["srcSysCd"],
                "srcAcctId": meter["account"]["srcAcctId"],
                "srcAcctId2": meter["account"]["srcAcctId2"] or "",
                "meterSerialNumber": meter["serialNum"],
                "serviceType": meter["serviceType"],
                "intervalFrequency": interval,
                "periodType": period,
                "date": start_date.strftime(_DATE_FORMAT),
                "includeWeatherData": "true" if include_temperature else "false",
                "agrmtStartDt": datetime.strptime(
                    meter["agreementActiveDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "agrmtEndDt": datetime.strptime(
                    meter["agreementEndDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "meterCertDt": datetime.strptime(
                    meter["meterCertificationDate"], "%Y-%m-%d"
                ).strftime(_DATE_FORMAT),
                "startDate": start_date.strftime(_DATE_FORMAT),
                "endDate": end_date.strftime(_DATE_FORMAT),
                "zipCode": meter["account"]["serviceAddressParsed"]["zipCode"],
                "showYear": "true",
            },
        )
        # map results to an object from start to end date by interval with values from
        # result["Series1"] array for energy and result["Series3"] array for temperature
        # first, loop through a range of dates from start to end date by interval
        tick_series = result["TickSeries"]
        energy = result["Series1"]
        temp = result["Series3"]

        tick_series, energy, temp = _remove_duplicates(tick_series, energy, temp)
        energy_len = len(energy)
        temp_len = len(temp)
        num_values = (end_date - start_date).days + 1

        # if interval is hourly, multiply the number of values by 24 and repeat the
        # temperature values for each hour
        if interval == "HOURLY":
            num_values = num_values * 24
            temp = [t for t in temp for _ in range(24)]
            temp_len = len(temp)

        data = {}
        missing = []
        offset = 0
        for i in range(num_values):
            delta = timedelta(hours=i) if interval == "HOURLY" else timedelta(days=i)
            date = start_date + delta
            n = i - offset

            expected_series = (
                date.strftime("%I %p")
                if interval == "HOURLY"
                else date.strftime("%m/%d/%Y")
            )
            if tick_series[n] != expected_series:
                missing.append(date)
                offset += 1
                continue

            if n >= energy_len or not energy[n] > 0:
                missing.append(date)
                continue

            data[date] = {
                "energy": energy[n] if n < energy_len else None,
                "temperature": temp[n] if n < temp_len else None,
            }

        return {"data": data, "missing": missing}

    async def _get_json(
        self, url: yarl.URL, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Get JSON from the Duke Energy API."""
        await self._validate_auth()
        if not self._auth:
            raise ValueError("Authentication failed")

        _LOGGER.debug("Calling %s with params: %s", url, params)
        response = await self.session.get(
            url,
            headers={"Authorization": f"Bearer {self._auth['access_token']}"},
            params=params or {},
            timeout=self.timeout,
        )
        _LOGGER.debug("Response from %s: %s", url, response.status)
        response.raise_for_status()
        json = await response.json()
        _LOGGER.debug("JSON from %s: %s", url, json)
        return json

    def _remove_duplicates(
        tick_series: List[str], 
        energy: List[str], 
        temp: List[str]
    ) -> Tuple[List[str], List[str], List[str]]:
        """Detects and removes duplicate reporting times and their respective data entries. """
        seen = set()
        new_tick_series = []
        new_energy = []
        new_temp = []
        for i, item in enumerate(tick_series):
            if item not in seen:
                seen.add(item)
                new_tick_series.append(item)
                if energy:
                    new_energy.append(energy[i])
                if temp:
                    new_temp.append(temp[i])
        return new_tick_series, new_energy, new_temp

    async def _validate_auth(self) -> None:
        """Validate the authentication tokens and fetch new ones if necessary."""
        if self._auth:
            issued_at = datetime.fromtimestamp(
                int(self._auth["issued_at"]) / 1000, timezone.utc
            )
            expires_in = int(self._auth["expires_in"])
            reauth = issued_at + timedelta(seconds=expires_in) < datetime.now(
                timezone.utc
            )

        if self._auth and not reauth:
            return

        await self.authenticate()
