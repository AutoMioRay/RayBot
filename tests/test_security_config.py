from __future__ import annotations

import pytest

from RayBot import BotConfig, HTTPConfig
from RayBot.core.errors import ConfigurationError


def test_https_is_required_for_non_loopback_base_url() -> None:
    with pytest.raises(ConfigurationError):
        HTTPConfig(base_url="http://example.com")

    local = HTTPConfig(base_url="http://127.0.0.1:8080")
    assert local.base_url == "http://127.0.0.1:8080"

    explicit = HTTPConfig(base_url="http://example.com", allow_insecure_http=True)
    assert explicit.allow_insecure_http


def test_base_url_must_not_contain_credentials() -> None:
    with pytest.raises(ConfigurationError):
        HTTPConfig(base_url="https://user:password@example.com")


def test_bot_config_repr_hides_secret() -> None:
    config = BotConfig(app_id="102124350", client_secret="TOP-SECRET-VALUE")
    rendered = repr(config)
    assert "TOP-SECRET-VALUE" not in rendered
    assert "app_id='102124350'" in rendered


def test_bot_config_rejects_empty_credentials() -> None:
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="", client_secret="secret")
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="app", client_secret="")


def test_bot_config_rejects_control_characters() -> None:
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="app\r\nINJECTED", client_secret="secret")
    with pytest.raises(ConfigurationError):
        BotConfig(
            app_id="app",
            client_secret="secret\nLOG-INJECTION",  # secret-scan: allow - fixture
        )


def test_bot_config_rejects_oversized_credentials() -> None:
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="a" * 65, client_secret="secret")
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="app", client_secret="s" * 257)


def test_bot_config_rejects_padded_credentials() -> None:
    with pytest.raises(ConfigurationError):
        BotConfig(app_id=" app ", client_secret="secret")
    with pytest.raises(ConfigurationError):
        BotConfig(app_id="app", client_secret=" secret ")
