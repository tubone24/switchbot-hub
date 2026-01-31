#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Google Nest Device Access OAuth2 authentication helper.

This script helps you obtain the refresh_token needed for the Google Nest API.

Prerequisites:
1. Register for Device Access ($5 one-time fee)
   https://developers.google.com/nest/device-access/registration
2. Create a Google Cloud Project and enable SDM API
3. Create OAuth 2.0 Client ID (Desktop app type)
4. Note your Device Access Project ID (UUID)

Usage:
    python google_nest_auth.py

The script will guide you through the OAuth2 flow.
"""
import json
import sys
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

import requests


def get_authorization_url(project_id, client_id, redirect_uri):
    """
    Generate the authorization URL for Google Nest Device Access.

    Args:
        project_id: Device Access project ID
        client_id: OAuth2 client ID
        redirect_uri: Redirect URI (use urn:ietf:wg:oauth:2.0:oob for desktop apps)

    Returns:
        str: Authorization URL
    """
    # Partner Connections Manager URL
    base_url = "https://nestservices.google.com/partnerconnections/{}/auth".format(project_id)

    params = {
        'redirect_uri': redirect_uri,
        'client_id': client_id,
        'access_type': 'offline',
        'prompt': 'consent',
        'response_type': 'code',
        'scope': 'https://www.googleapis.com/auth/sdm.service'
    }

    return "{}?{}".format(base_url, urlencode(params))


def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri):
    """
    Exchange authorization code for access and refresh tokens.

    Args:
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret
        code: Authorization code from OAuth flow
        redirect_uri: Same redirect URI used in authorization

    Returns:
        dict: Token response with access_token and refresh_token
    """
    token_url = "https://oauth2.googleapis.com/token"

    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri
    }

    response = requests.post(token_url, data=data, timeout=30)
    response.raise_for_status()
    return response.json()


def main():
    print("=" * 60)
    print("Google Nest Device Access - OAuth2 Setup Helper")
    print("=" * 60)
    print()

    print("Before starting, make sure you have:")
    print("1. Registered for Device Access (https://developers.google.com/nest/device-access)")
    print("2. Created a Google Cloud Project with SDM API enabled")
    print("3. Created OAuth 2.0 Client ID (Desktop app type)")
    print()

    # Get credentials from user
    project_id = input("Enter your Device Access Project ID (UUID): ").strip()
    if not project_id:
        print("Error: Project ID is required")
        sys.exit(1)

    client_id = input("Enter your OAuth2 Client ID: ").strip()
    if not client_id:
        print("Error: Client ID is required")
        sys.exit(1)

    client_secret = input("Enter your OAuth2 Client Secret: ").strip()
    if not client_secret:
        print("Error: Client Secret is required")
        sys.exit(1)

    # Use OOB (Out-of-Band) redirect for desktop apps
    # This allows copy-pasting the code instead of setting up a local server
    redirect_uri = "urn:ietf:wg:oauth:2.0:oob"

    # Generate authorization URL
    auth_url = get_authorization_url(project_id, client_id, redirect_uri)

    print()
    print("=" * 60)
    print("Step 1: Authorize access")
    print("=" * 60)
    print()
    print("Opening browser to authorize access...")
    print("If browser doesn't open, copy this URL:")
    print()
    print(auth_url)
    print()

    # Try to open browser
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("After authorizing, you'll see a page with an authorization code.")
    print()

    code = input("Paste the authorization code here: ").strip()
    if not code:
        print("Error: Authorization code is required")
        sys.exit(1)

    # Exchange code for tokens
    print()
    print("Exchanging code for tokens...")

    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, code, redirect_uri)
    except requests.exceptions.HTTPError as e:
        print("Error: Failed to exchange code for tokens")
        print("Response: {}".format(e.response.text))
        sys.exit(1)

    print()
    print("=" * 60)
    print("Success! Here are your credentials:")
    print("=" * 60)
    print()

    config = {
        "google_nest": {
            "enabled": True,
            "project_id": project_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens.get('refresh_token'),
            "credentials_file": None,
            "interval_seconds": 300
        }
    }

    print(json.dumps(config, indent=4))
    print()
    print("Copy the above configuration to your config.json file.")
    print()

    # Save to file option
    save = input("Save credentials to google_nest_credentials.json? (y/n): ").strip().lower()
    if save == 'y':
        creds = {
            'project_id': project_id,
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': tokens.get('refresh_token')
        }
        with open('google_nest_credentials.json', 'w') as f:
            json.dump(creds, f, indent=2)
        print("Saved to google_nest_credentials.json")
        print()
        print("IMPORTANT: Keep this file secure and add it to .gitignore!")

    print()
    print("Setup complete!")


if __name__ == '__main__':
    main()
