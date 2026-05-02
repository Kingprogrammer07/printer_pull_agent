import base64
import hashlib
import hmac
import time
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import Response

from app.core.config import Settings


@dataclass
class LoginAttempt:
    failures: int = 0
    locked_until: float = 0.0


class AuthManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._attempts: dict[str, LoginAttempt] = {}

    def client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return request.client.host if request.client else "unknown"

    def lock_remaining_seconds(self, key: str) -> int:
        attempt = self._attempts.get(key)
        if attempt is None:
            return 0
        remaining = int(attempt.locked_until - time.time())
        if remaining <= 0:
            if attempt.locked_until:
                self._attempts.pop(key, None)
            return 0
        return remaining

    def verify_credentials(self, username: str, password: str, key: str) -> bool:
        if self.lock_remaining_seconds(key) > 0:
            return False
        valid_username = hmac.compare_digest(username, self.settings.admin_username)
        valid_password = hmac.compare_digest(password, self.settings.admin_password)
        if valid_username and valid_password:
            self._attempts.pop(key, None)
            return True
        self.record_failure(key)
        return False

    def record_failure(self, key: str) -> None:
        attempt = self._attempts.setdefault(key, LoginAttempt())
        attempt.failures += 1
        if attempt.failures >= self.settings.login_lock_failures:
            attempt.locked_until = time.time() + self.settings.login_lock_minutes * 60

    def create_token(self, username: str) -> str:
        expires_at = int(time.time() + self.settings.auth_session_hours * 3600)
        payload = f"{username}:{expires_at}".encode("utf-8")
        encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii")
        signature = self._sign(encoded_payload)
        return f"{encoded_payload}.{signature}"

    def is_authenticated(self, request: Request) -> bool:
        token = request.cookies.get(self.settings.auth_cookie_name)
        if not token or "." not in token:
            return False
        encoded_payload, signature = token.rsplit(".", 1)
        expected_signature = self._sign(encoded_payload)
        if not hmac.compare_digest(signature, expected_signature):
            return False
        try:
            decoded = base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8")
            username, expires_at_text = decoded.rsplit(":", 1)
            expires_at = int(expires_at_text)
        except (ValueError, UnicodeDecodeError):
            return False
        return (
            hmac.compare_digest(username, self.settings.admin_username)
            and expires_at > int(time.time())
        )

    def set_login_cookie(self, response: Response) -> None:
        response.set_cookie(
            self.settings.auth_cookie_name,
            self.create_token(self.settings.admin_username),
            max_age=self.settings.auth_session_hours * 3600,
            httponly=True,
            secure=self.settings.auth_cookie_secure,
            samesite="lax",
        )

    def clear_login_cookie(self, response: Response) -> None:
        response.delete_cookie(self.settings.auth_cookie_name)

    def _sign(self, encoded_payload: str) -> str:
        secret = self.settings.auth_secret or self.settings.admin_password
        return hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()
