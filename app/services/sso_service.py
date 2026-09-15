"""SSO service — OIDC provider abstraction (Business+ feature).

Provides the structure for SSO login via Google, Microsoft, GitHub.
Since we're running locally (no public callback URL), this is a scaffold
that can be activated when deploying with a public domain.

For OIDC, requires: PMO_SSO_GOOGLE_CLIENT_ID, PMO_SSO_GOOGLE_CLIENT_SECRET, etc.
"""
import secrets
from dataclasses import dataclass


@dataclass
class SSOProvider:
    """Configuration for an OIDC provider."""
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: list


# Provider configurations (loaded from env vars when set)
_PROVIDERS = {
    "google": SSOProvider(
        name="google",
        client_id="",
        client_secret="",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        scopes=["openid", "email", "profile"],
    ),
    "microsoft": SSOProvider(
        name="microsoft",
        client_id="",
        client_secret="",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
        scopes=["openid", "email", "profile"],
    ),
    "github": SSOProvider(
        name="github",
        client_id="",
        client_secret="",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scopes=["user:email"],
    ),
}


def get_provider(name: str) -> SSOProvider | None:
    """Get an SSO provider configuration."""
    provider = _PROVIDERS.get(name)
    if not provider:
        return None

    # Load credentials from env vars
    import os
    prefix = f"PMO_SSO_{name.upper()}"
    client_id = os.environ.get(f"{prefix}_CLIENT_ID", "")
    client_secret = os.environ.get(f"{prefix}_CLIENT_SECRET", "")

    if not client_id:
        return None  # Provider not configured

    provider.client_id = client_id
    provider.client_secret = client_secret
    return provider


def get_authorization_url(provider_name: str, redirect_uri: str, state: str = None) -> str:
    """Build the authorization URL for an OIDC provider."""
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"SSO provider '{provider_name}' is not configured.")

    state = state or secrets.token_urlsafe(32)
    params = "&".join([
        f"client_id={provider.client_id}",
        f"redirect_uri={redirect_uri}",
        f"response_type=code",
        f"scope={' '.join(provider.scopes)}",
        f"state={state}",
    ])
    return f"{provider.authorize_url}?{params}"


def list_available_providers() -> list:
    """List configured SSO providers."""
    available = []
    for name in _PROVIDERS:
        if get_provider(name):
            available.append(name)
    return available
