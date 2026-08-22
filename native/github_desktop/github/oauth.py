"""Browser OAuth for GitHub.com and GitHub Enterprise."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlencode

from ..models import html_url_from_endpoint, api_endpoint_from_html
from ..version import OAUTH_CLIENT_ID_DEFAULT, OAUTH_CLIENT_SECRET_DEFAULT, OAUTH_SCOPES
from .api import GitHubAPI, get_dotcom_api_endpoint, request_oauth_token


def oauth_client_id() -> str:
    return os.environ.get("DESKTOP_OAUTH_CLIENT_ID") or OAUTH_CLIENT_ID_DEFAULT


def oauth_client_secret() -> str:
    return os.environ.get("DESKTOP_OAUTH_CLIENT_SECRET") or OAUTH_CLIENT_SECRET_DEFAULT


def get_oauth_authorization_url(endpoint: str, state: str) -> str:
    html = html_url_from_endpoint(endpoint)
    query = urlencode(
        {
            "client_id": oauth_client_id(),
            "scope": " ".join(OAUTH_SCOPES),
            "state": state,
        }
    )
    return f"{html}/login/oauth/authorize?{query}"


def new_oauth_state() -> str:
    return str(uuid.uuid4())


def exchange_code_for_account(endpoint: str, code: str):
    html = html_url_from_endpoint(endpoint)
    token = request_oauth_token(html, oauth_client_id(), oauth_client_secret(), code)
    if not token:
        return None
    api = GitHubAPI(endpoint, token)
    return api.fetch_account(token)


def dotcom_endpoint() -> str:
    return get_dotcom_api_endpoint()


def enterprise_endpoint_from_url(url: str) -> str:
    return api_endpoint_from_html(url)
