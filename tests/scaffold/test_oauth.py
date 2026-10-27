import json
import stat

import pytest
from microdex.oauth import (
    CLIENT_ID,
    REDIRECT_URI,
    CallbackError,
    authorization_code_form,
    authorize_url,
    callback_html,
    current_access_token,
    make_pkce,
    parse_callback,
    resolve_api_key,
    save_auth,
)

pytestmark = pytest.mark.scaffold


def test_pkce_challenge_is_s256_without_padding():
    import base64
    import hashlib

    verifier, challenge = make_pkce()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert "=" not in challenge


def test_authorize_url_uses_the_registered_loopback_client():
    url = authorize_url(challenge="chal", state="state-1", nonce="nonce-1")
    assert url.startswith("https://auth.x.ai/oauth2/authorize?")
    assert f"client_id={CLIENT_ID}" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A56121%2Fcallback" in url
    assert REDIRECT_URI == "http://127.0.0.1:56121/callback"
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "state=state-1" in url


def test_token_form_repeats_the_pkce_challenge():
    form = authorization_code_form("code-1", "verifier", "chal")
    assert form["grant_type"] == "authorization_code"
    assert form["code"] == "code-1"
    assert form["code_verifier"] == "verifier"
    assert form["code_challenge"] == "chal"
    assert form["redirect_uri"] == REDIRECT_URI


def test_callback_rejects_a_mismatched_state_and_escapes_html():
    with pytest.raises(CallbackError, match="did not match"):
        parse_callback("/callback?code=abc&state=other", "expected")
    assert parse_callback("/callback?code=abc&state=expected", "expected") == "abc"
    assert "<script>" not in callback_html("<script>")


def test_saved_login_is_private_and_refreshes_only_when_due(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    monkeypatch.setenv("MICRODEX_AUTH_FILE", str(path))
    save_auth(
        {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_at": 10_000,
        },
        path,
    )
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

    calls = []

    def post(url, fields):
        calls.append((url, fields))
        return {
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
        }

    assert current_access_token(now=100, post=post) == "access-1"
    assert calls == []
    assert current_access_token(now=9_900, post=post) == "access-2"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "refresh-2"
    assert calls[0][1]["grant_type"] == "refresh_token"
    assert calls[0][1]["refresh_token"] == "refresh-1"


def test_env_key_wins_and_logout_removes_the_file(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    monkeypatch.setenv("MICRODEX_AUTH_FILE", str(path))
    save_auth(
        {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_at": 10**12,
        },
        path,
    )
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    assert resolve_api_key() == "xai-test"
    monkeypatch.delenv("XAI_API_KEY")
    assert resolve_api_key() == "access-1"

    from microdex.cli import main

    assert main(["logout"]) == 0
    assert not path.exists()
    assert main(["logout"]) == 0
