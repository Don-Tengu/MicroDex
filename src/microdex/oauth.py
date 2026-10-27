"""Sign in with a SuperGrok subscription.

xAI publishes a public OAuth client for Grok CLI tools. OpenCode uses the same
client: PKCE on a loopback redirect, no client secret. The access token is a
bearer token for https://api.x.ai/v1. Discovery lives at
https://auth.x.ai/.well-known/openid-configuration.

The redirect port is part of the registered client. A random port will be
rejected. 56121 is also what OpenCode binds, so a second login cannot share it.
"""

import base64
import hashlib
import html
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
SCOPE = "openid profile email offline_access grok-cli:access api:access"
REDIRECT_URI = "http://127.0.0.1:56121/callback"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 56121
ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
DEFAULT_AUTHORIZE_URL = f"{ISSUER}/oauth2/authorize"
DEFAULT_TOKEN_URL = f"{ISSUER}/oauth2/token"
REFRESH_SKEW_SECONDS = 5 * 60
LOGIN_TIMEOUT_SECONDS = 180

PostForm = Callable[[str, dict[str, str]], dict]


class OAuthError(RuntimeError):
    pass


class CallbackError(OAuthError):
    pass


def auth_path() -> Path:
    override = os.environ.get("MICRODEX_AUTH_FILE")
    if override:
        return Path(override)
    return Path.home() / ".microdex" / "auth.json"


def make_pkce() -> tuple[str, str]:
    """Return `(verifier, S256 challenge)`."""

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorize_url(
    *,
    challenge: str,
    state: str,
    nonce: str,
    authorization_endpoint: str = DEFAULT_AUTHORIZE_URL,
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "plan": "generic",
            "referrer": "microdex",
        }
    )
    return f"{authorization_endpoint}?{query}"


def authorization_code_form(code: str, verifier: str, challenge: str) -> dict[str, str]:
    """xAI checks the PKCE challenge again at the token endpoint."""

    return {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


def parse_callback(path: str, expected_state: str) -> str:
    """Pull the authorization code out of the loopback request."""

    parsed = urlparse(path)
    if parsed.path != "/callback":
        raise CallbackError("Unexpected callback path")
    query = parse_qs(parsed.query)
    error = _first(query, "error")
    if error:
        description = _first(query, "error_description")
        raise CallbackError(description or error)
    state = _first(query, "state")
    if not secrets.compare_digest(state, expected_state):
        raise CallbackError("Login state did not match. Run microdex login again.")
    code = _first(query, "code")
    if not code:
        raise CallbackError("Login callback did not include a code")
    return code


def callback_html(message: str) -> str:
    safe = html.escape(message, quote=True)
    return f"<!doctype html><title>Microdex</title><p>{safe}</p>"


def save_auth(auth: dict, path: Path | None = None) -> Path:
    """Write the token file so only this user can read it."""

    target = path or auth_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)
    temporary = target.with_suffix(".json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(auth).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(temporary, target)
    os.chmod(target, 0o600)
    return target


def load_auth(path: Path | None = None) -> dict | None:
    target = path or auth_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OAuthError(f"Saved login is unreadable. Run microdex login again. ({exc})") from exc
    if not isinstance(data, dict) or not data.get("access_token") or not data.get("refresh_token"):
        raise OAuthError("Saved login is incomplete. Run microdex login again.")
    return data


def delete_auth(path: Path | None = None) -> bool:
    target = path or auth_path()
    if not target.is_file():
        return False
    target.unlink()
    return True


def token_from_response(body: dict, *, now: float, previous_refresh: str = "") -> dict:
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        raise OAuthError("Token response did not include an access token")
    refresh = body.get("refresh_token") or previous_refresh
    if not isinstance(refresh, str) or not refresh:
        raise OAuthError("Token response did not include a refresh token")
    expires_in = body.get("expires_in", 3600)
    if not isinstance(expires_in, (int, float)) or expires_in <= 0:
        raise OAuthError("Token response did not include a positive expires_in")
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": int(now + expires_in),
    }


def current_access_token(
    *,
    now: float | None = None,
    post: PostForm | None = None,
) -> str:
    """Return a usable access token, refreshing when it is inside the skew window."""

    saved = load_auth()
    if saved is None:
        raise OAuthError(
            "No SuperGrok login. Run `microdex login`, or set XAI_API_KEY."
        )
    moment = time.time() if now is None else now
    expires_at = saved.get("expires_at", 0)
    if isinstance(expires_at, (int, float)) and expires_at - moment > REFRESH_SKEW_SECONDS:
        return str(saved["access_token"])
    refreshed = refresh_auth(str(saved["refresh_token"]), now=moment, post=post)
    save_auth(refreshed)
    return str(refreshed["access_token"])


def resolve_api_key(explicit: str | None = None) -> str:
    """Explicit key, then `XAI_API_KEY`, then the saved SuperGrok token."""

    if explicit:
        return explicit
    env = os.environ.get("XAI_API_KEY") or ""
    if env:
        return env
    return current_access_token()


def refresh_auth(
    refresh_token: str,
    *,
    now: float | None = None,
    post: PostForm | None = None,
    token_endpoint: str = DEFAULT_TOKEN_URL,
) -> dict:
    sender = post or post_form
    body = sender(
        token_endpoint,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )
    return token_from_response(body, now=time.time() if now is None else now, previous_refresh=refresh_token)


def exchange_authorization_code(
    code: str,
    verifier: str,
    challenge: str,
    *,
    now: float | None = None,
    post: PostForm | None = None,
    token_endpoint: str = DEFAULT_TOKEN_URL,
) -> dict:
    sender = post or post_form
    body = sender(token_endpoint, authorization_code_form(code, verifier, challenge))
    return token_from_response(body, now=time.time() if now is None else now)


def login() -> Path:
    """Open the browser, catch the loopback redirect, and store the tokens."""

    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    authorize, token_endpoint = _endpoints()
    url = authorize_url(
        challenge=challenge,
        state=state,
        nonce=nonce,
        authorization_endpoint=authorize,
    )
    print("Opening the browser to sign in with SuperGrok.", file=sys.stderr)
    print("If it does not open, visit:", file=sys.stderr)
    print(url, file=sys.stderr)
    try:
        code = _capture_code(state, url)
    except OSError as exc:
        raise OAuthError(
            "Port 56121 is in use. Close the other Grok login (OpenCode uses this port) and retry."
        ) from exc
    saved = exchange_authorization_code(code, verifier, challenge, token_endpoint=token_endpoint)
    return save_auth(saved)


def post_form(url: str, fields: dict[str, str]) -> dict:
    data = urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = _oauth_error_message(detail) or detail.strip()
        raise OAuthError(f"xAI token request failed (HTTP {exc.code}): {message}") from exc
    except urllib.error.URLError as exc:
        raise OAuthError(f"xAI token request failed: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise OAuthError("xAI token response was not a JSON object")
    if "error" in payload:
        description = payload.get("error_description") or payload["error"]
        raise OAuthError(f"xAI token request failed: {description}")
    return payload


def _endpoints() -> tuple[str, str]:
    """Prefer discovery, and refuse an authorization server that is not auth.x.ai."""

    try:
        with urllib.request.urlopen(DISCOVERY_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        authorize = str(payload["authorization_endpoint"])
        token = str(payload["token_endpoint"])
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_AUTHORIZE_URL, DEFAULT_TOKEN_URL
    if not authorize.startswith(f"{ISSUER}/") or not token.startswith(f"{ISSUER}/"):
        raise OAuthError("xAI discovery returned an unexpected authorization server")
    return authorize, token


def _capture_code(expected_state: str, url: str) -> str:
    held: dict[str, str] = {}
    failed: dict[str, CallbackError] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlparse(self.path).path != "/callback":
                _write_html(self, 404, "Not found")
                return
            try:
                held["code"] = parse_callback(self.path, expected_state)
            except CallbackError as exc:
                failed["error"] = exc
                _write_html(self, 400, str(exc))
                return
            _write_html(self, 200, "Signed in. You can close this tab.")

        def log_message(self, fmt: str, *args) -> None:
            # The query string contains the authorization code.
            return

    server = ThreadingHTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    server.timeout = 0.5
    webbrowser.open(url)
    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
    try:
        while "code" not in held and "error" not in failed:
            if time.time() > deadline:
                raise OAuthError("Login timed out. Run microdex login again.")
            server.handle_request()
    finally:
        server.server_close()
    if "error" in failed and "code" not in held:
        raise failed["error"]
    return held["code"]


def _write_html(handler: BaseHTTPRequestHandler, status: int, message: str) -> None:
    body = callback_html(message).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return values[0] if values else ""


def _oauth_error_message(raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    description = payload.get("error_description") or payload.get("error") or ""
    return str(description)
