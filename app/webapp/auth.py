from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class WebAppAuthError(Exception):
    """Invalid or expired Telegram Mini App launch credentials."""


@dataclass(slots=True)
class WebAppUser:
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


def verify_init_data(
    init_data: str, bot_token: str, *, max_age: int = 3600, now: float | None = None
) -> WebAppUser:
    if not init_data or not bot_token or len(init_data) > 16384:
        raise WebAppAuthError("Откройте приложение заново через Telegram.")
    fields = parse_qsl(init_data, keep_blank_values=True)
    if len({key for key, _ in fields}) != len(fields):
        raise WebAppAuthError("Некорректные данные авторизации.")
    parsed = dict(fields)
    received_hash = parsed.pop("hash", "")
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if (
        len(received_hash) != 64
        or not received_hash.isascii()
        or not hmac.compare_digest(expected, received_hash)
    ):
        raise WebAppAuthError("Не удалось подтвердить вход через Telegram.")
    try:
        auth_date = int(parsed["auth_date"])
        payload = json.loads(parsed["user"])
        if not isinstance(payload, dict):
            raise ValueError("Invalid user")
        user_id = payload.get("id")
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise ValueError("Invalid user id")
        current = time.time() if now is None else now
        if auth_date > current + 30 or current - auth_date > max_age:
            raise WebAppAuthError("Сессия истекла. Закройте приложение и откройте его из бота.")
        return WebAppUser(
            id=user_id,
            **{
                key: payload.get(key) if isinstance(payload.get(key), str) else None
                for key in ("first_name", "last_name", "username")
            },
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise WebAppAuthError("Некорректные данные авторизации Telegram.") from exc
