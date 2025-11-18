from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class WebAppAuthError(Exception):
    """Raised when Telegram WebApp init data cannot be verified."""


@dataclass(slots=True)
class WebAppUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


def verify_init_data(init_data: str, bot_token: str) -> WebAppUser:
    """Validate Telegram initData string and return parsed user info."""
    if not init_data:
        raise WebAppAuthError("Missing initData")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise WebAppAuthError("Missing hash")

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(parsed.items(), key=lambda item: item[0])
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise WebAppAuthError("Invalid initData signature")

    user_data_raw = parsed.get("user")
    if not user_data_raw:
        raise WebAppAuthError("Missing user data")

    user_payload: dict[str, Any] = json.loads(user_data_raw)
    user_id = user_payload.get("id")
    if not isinstance(user_id, int):
        raise WebAppAuthError("Invalid user id")

    return WebAppUser(
        id=user_id,
        first_name=user_payload.get("first_name"),
        last_name=user_payload.get("last_name"),
        username=user_payload.get("username"),
    )
