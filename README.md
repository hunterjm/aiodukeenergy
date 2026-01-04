# aiodukeenergy

<p align="center">
  <a href="https://github.com/hunterjm/aiodukeenergy/actions/workflows/ci.yml?query=branch%3Amain">
    <img src="https://img.shields.io/github/actions/workflow/status/hunterjm/aiodukeenergy/ci.yml?branch=main&label=CI&logo=github&style=flat-square" alt="CI Status" >
  </a>
  <a href="https://aiodukeenergy.readthedocs.io">
    <img src="https://img.shields.io/readthedocs/aiodukeenergy.svg?logo=read-the-docs&logoColor=fff&style=flat-square" alt="Documentation Status">
  </a>
  <a href="https://codecov.io/gh/hunterjm/aiodukeenergy">
    <img src="https://img.shields.io/codecov/c/github/hunterjm/aiodukeenergy.svg?logo=codecov&logoColor=fff&style=flat-square" alt="Test coverage percentage">
  </a>
</p>
<p align="center">
  <a href="https://python-poetry.org/">
    <img src="https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json" alt="Poetry">
  </a>
  <a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
  </a>
  <a href="https://github.com/pre-commit/pre-commit">
    <img src="https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=flat-square" alt="pre-commit">
  </a>
</p>
<p align="center">
  <a href="https://pypi.org/project/aiodukeenergy/">
    <img src="https://img.shields.io/pypi/v/aiodukeenergy.svg?logo=python&logoColor=fff&style=flat-square" alt="PyPI Version">
  </a>
  <img src="https://img.shields.io/pypi/pyversions/aiodukeenergy.svg?style=flat-square&logo=python&amp;logoColor=fff" alt="Supported Python versions">
  <img src="https://img.shields.io/pypi/l/aiodukeenergy.svg?style=flat-square" alt="License">
</p>

---

**Documentation**: <a href="https://aiodukeenergy.readthedocs.io" target="_blank">https://aiodukeenergy.readthedocs.io </a>

**Source Code**: <a href="https://github.com/hunterjm/aiodukeenergy" target="_blank">https://github.com/hunterjm/aiodukeenergy </a>

---

Asyncio Duke Energy

## Installation

Install this via pip (or your favourite package manager):

`pip install aiodukeenergy`

## Usage

Duke Energy uses Auth0 with CAPTCHA protection which blocks automated logins.
Authentication requires a browser-based OAuth flow using a Chrome extension to
capture the mobile app's custom redirect URL.

### Setup

1. Install the Chrome extension:

   - Download the [latest chrome-extension.zip](https://github.com/hunterjm/aiodukeenergy/releases/latest/download/chrome-extension.zip) from releases (or use `./chrome-extension/` from source)
   - Extract the zip file
   - Open Chrome and navigate to `chrome://extensions/`
   - Enable "Developer mode"
   - Click "Load unpacked" and select the extracted folder

2. Run the browser authentication script:

   ```bash
   cd examples
   python browser_auth.py
   ```

3. The script will:
   - Open your browser to Duke Energy's login page
   - After you log in, the extension captures the authorization code
   - Exchange the code for API tokens
   - Save tokens to `duke_tokens.json`

### Using Tokens

Once you have tokens, use them with the library:

```python
import asyncio
import aiohttp
from aiodukeenergy import Auth0Client, DukeEnergy, DukeEnergyAuth


async def main():
    # Option 1: Load from token file
    import json

    with open("duke_tokens.json") as f:
        tokens = json.load(f)

    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(
            session,
            auth0_client,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            id_token=tokens.get("id_token"),
        )

        client = DukeEnergy(auth)

        accounts = await client.get_accounts()
        print(accounts)

        meters = await client.get_meters()
        for serial, meter in meters.items():
            print(f"Meter: {serial} ({meter['serviceType']})")


asyncio.run(main())
```

### Browser OAuth Flow (Programmatic)

You can also integrate the OAuth flow into your own application:

```python
import asyncio
import webbrowser
import aiohttp
from aiodukeenergy import Auth0Client, DukeEnergy, DukeEnergyAuth


async def main():
    async with aiohttp.ClientSession() as session:
        auth0_client = Auth0Client(session)
        auth = DukeEnergyAuth(session, auth0_client)

        # Step 1: Get authorization URL with PKCE
        auth_url, state, code_verifier = auth0_client.get_authorization_url()

        # Step 2: Open browser for user login
        webbrowser.open(auth_url)

        # Step 3: Get the authorization code (captured by Chrome extension)
        code = input("Enter the authorization code: ")

        # Step 4: Exchange code for tokens
        await auth.authenticate_with_code(code, code_verifier)

        # Now you can make API calls
        client = DukeEnergy(auth)
        accounts = await client.get_accounts()
        print(accounts)


asyncio.run(main())
```

### Available Classes

- `Auth0Client` - OAuth2/OIDC client for Duke Energy's Auth0
  - `get_authorization_url()` - Generate browser OAuth URL with PKCE (returns url, state, code_verifier)
  - `exchange_code(code, code_verifier)` - Exchange authorization code for tokens
  - `refresh_token(refresh_token)` - Refresh expired tokens
- `AbstractDukeEnergyAuth` - Abstract base class for auth providers
  - `async_get_id_token()` - Get a valid ID token (abstract)
  - `async_get_access_token()` - Get a valid access token
  - `request(method, url, **kwargs)` - Make authenticated requests
- `DukeEnergyAuth` - Concrete auth implementation using Auth0Client
  - `authenticate_with_code(code, code_verifier)` - Complete OAuth flow
  - `token` - Property to get current token dictionary
- `DukeEnergy` - API client for Duke Energy
  - `get_accounts()` - Get all accounts
  - `get_meters()` - Get all meters
  - `get_energy_usage(meter_serial, interval, view, start_date, end_date)` - Get usage data

## Contributors ✨

Thanks goes to these wonderful people ([emoji key](https://allcontributors.org/docs/en/emoji-key)):

<!-- prettier-ignore-start -->
<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- markdownlint-disable -->
<!-- markdownlint-enable -->
<!-- ALL-CONTRIBUTORS-LIST:END -->
<!-- prettier-ignore-end -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!

## Credits

This package was created with
[Copier](https://copier.readthedocs.io/) and the
[browniebroke/pypackage-template](https://github.com/browniebroke/pypackage-template)
project template.
