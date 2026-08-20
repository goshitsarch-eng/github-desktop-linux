"""Application identity and version (matches Electron Desktop 3.5.4 feature set)."""

__version__ = "3.5.4"
APP_NAME = "GitHub Desktop"
APP_ID = "io.github.desktop.GitHubDesktop"
BUNDLE_ID = "com.github.GitHubClient"
COMPANY = "GitHub, Inc."
PRODUCT_NAME = "GitHub Desktop"
OAUTH_CLIENT_ID_DEFAULT = "3a723b10ac5575cc5bb9"
OAUTH_CLIENT_SECRET_DEFAULT = "22c34d87789a365981ed921352a7b9a8c3f69d54"
OAUTH_SCOPES = ("repo", "user", "workflow")
PROTOCOL_SCHEMES = (
    "x-github-client",
    "x-github-desktop-auth",
    "x-github-desktop-dev-auth",
)
