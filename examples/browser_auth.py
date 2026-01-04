#!/usr/bin/env python3
"""
Browser-based OAuth authentication helper for Duke Energy.

This script handles the OAuth flow for Duke Energy's mobile API:
1. Generates PKCE challenge and opens browser for login
2. User logs in and uses Chrome extension to capture the redirect code
3. Script exchanges the authorization code for Duke Energy API tokens

Prerequisites:
    - Install the Chrome extension from examples/chrome-extension/
    - See examples/chrome-extension/README.md for installation instructions

Usage:
    python browser_auth.py
"""

import asyncio
import json
import sys
import webbrowser

import aiohttp

from aiodukeenergy import Auth0Client, DukeEnergy, DukeEnergyAuth, DukeEnergyAuthError


async def main() -> None:
    """Run the browser-based OAuth flow."""
    print("=" * 60)
    print("Duke Energy Browser OAuth Helper")
    print("=" * 60)
    print()
    print("Prerequisites:")
    print("  1. Install the Chrome extension from examples/chrome-extension/")
    print("  2. Load it as an unpacked extension in chrome://extensions/")
    print()

    async with aiohttp.ClientSession() as session:
        # Create Auth0 client
        auth0_client = Auth0Client(session)

        # Step 1: Get authorization URL
        print("Step 1: Generating authorization URL...")
        auth_url, _state, code_verifier = auth0_client.get_authorization_url()

        print()
        print("Step 2: Opening browser for login...")
        print()
        print("If the browser doesn't open, manually visit this URL:")
        print()
        print(auth_url)
        print()

        # Try to open browser
        webbrowser.open(auth_url)

        print("-" * 60)
        print("INSTRUCTIONS:")
        print("-" * 60)
        print()
        print("1. Log in with your Duke Energy credentials")
        print("2. Complete any MFA/verification steps")
        print("3. After login, the Chrome extension will capture the code")
        print("4. Copy the authorization code from the extension page")
        print("5. Paste the code below")
        print()
        print("Enter the authorization code:")
        code = input("> ").strip()

        if not code:
            print("Error: No code provided")
            sys.exit(1)

        print()
        print("Step 3: Exchanging code for Duke Energy tokens...")

        try:
            # Create auth and authenticate
            auth = DukeEnergyAuth(session, auth0_client)
            await auth.authenticate_with_code(code, code_verifier)

            # Get token dict for display/saving
            token_data = auth.token
            access_token = token_data.get("access_token", "") if token_data else ""
            refresh_token = token_data.get("refresh_token", "") if token_data else ""
            id_token = token_data.get("id_token", "") if token_data else ""

            print()
            print("=" * 60)
            print("SUCCESS! Tokens obtained:")
            print("=" * 60)
            print()
            print(f"User ID: {auth.internal_user_id}")
            print(f"Email: {auth.email}")
            print()
            print(f"Access Token ({len(access_token)} chars):")
            print(f"  {access_token[:50]}...{access_token[-20:]}")
            print()
            if refresh_token:
                print(f"Refresh Token ({len(refresh_token)} chars):")
                print(f"  {refresh_token[:50]}...{refresh_token[-20:]}")
                print()

            # Test fetching accounts
            print("-" * 60)
            print("Testing API access - fetching accounts...")
            client = DukeEnergy(auth)
            accounts = await client.get_accounts()
            print(f"Found {len(accounts)} account(s)")
            for account_num in accounts:
                print(f"  - {account_num}")
            print()

            # Offer to save tokens
            print("=" * 60)
            save = input("Save tokens to file? (y/n): ").strip().lower()
            if save == "y":
                filename = "duke_tokens.json"
                with open(filename, "w") as f:
                    json.dump(token_data, f, indent=2)
                print(f"Tokens saved to {filename}")

            print()
            print("Use these tokens with the library:")
            print()
            print("import aiohttp")
            print("from aiodukeenergy import Auth0Client, DukeEnergy, DukeEnergyAuth")
            print()
            print("async with aiohttp.ClientSession() as session:")
            print("    auth0_client = Auth0Client(session)")
            print("    auth = DukeEnergyAuth(")
            print("        session,")
            print("        auth0_client,")
            print(f'        access_token="{access_token[:30]}...",')
            print(f'        refresh_token="{refresh_token[:30]}...",')
            print(f'        id_token="{id_token[:30]}...",')
            print("    )")
            print("    client = DukeEnergy(auth)")
            print("    accounts = await client.get_accounts()")

        except DukeEnergyAuthError as e:
            print(f"Authentication error: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
