"""Local accounts, salted scrypt credentials and revocable opaque sessions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field

from blaster.store import now


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(min_length=1, max_length=256, repr=False)


class UserInput(Credentials):
    display_name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="operator", pattern=r"^(admin|operator|analyst)$")
    enabled: bool = True


def password_hash(password):
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return salt.hex() + ":" + key.hex()


def verify(password, encoded):
    salt, expected = encoded.split(":")
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
    return hmac.compare_digest(key.hex(), expected)


def safe_user(row):
    return {k: row[k] for k in ("id", "username", "display_name", "role", "enabled")}


class Security:
    def __init__(self, ops, settings):
        self.ops, self.db, self.settings = ops, ops.db, settings
        self.attempts = defaultdict(deque)
        self.dummy = password_hash(secrets.token_urlsafe(20))

    async def bootstrap(self, public_access: bool = False):
        if self.db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        if self.settings.bootstrap_username:
            payload = UserInput(
                username=self.settings.bootstrap_username,
                password=self.settings.bootstrap_password,
                display_name=self.settings.bootstrap_display_name,
                role="admin",
            )
            encoded = await asyncio.to_thread(password_hash, payload.password)
            uid = self.create(payload, encoded)
            self.ops.audit({"id": uid, "username": payload.username}, "auth.bootstrap", uid)
        elif public_access:
            raise ValueError(
                "Configura auth.bootstrap_username y auth.bootstrap_password en el TOML "
                "para crear el primer administrador antes de habilitar el dominio."
            )

    def user(self, token):
        if not self.settings.enabled:
            return {
                "id": None,
                "username": "local",
                "display_name": "Operador local",
                "role": "admin",
                "enabled": True,
            }
        if not token:
            return None
        row = self.db.execute(
            """SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1""",
            (hashlib.sha256(token.encode()).hexdigest(), now()),
        ).fetchone()
        return safe_user(row) if row else None

    def issue(self, uid):
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(hours=self.settings.session_hours)
        with self.db:
            self.db.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now(),))
            self.db.execute(
                "INSERT INTO auth_sessions VALUES(?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), uid, expires.isoformat(), now()),
            )
        return token

    def throttle(self, key):
        clock = time.monotonic()
        attempts = self.attempts[key]
        while attempts and attempts[0] < clock - 60:
            attempts.popleft()
        if len(attempts) >= 8:
            raise HTTPException(429, "Demasiados intentos. Espera un minuto.")
        attempts.append(clock)
        if len(self.attempts) > 1000:
            self.attempts = defaultdict(deque, {key: attempts})

    def create(self, payload, encoded):
        uid = uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                (
                    uid,
                    payload.username,
                    payload.display_name,
                    encoded,
                    payload.role,
                    int(payload.enabled),
                    now(),
                ),
            )
        return uid

    def revoke(self, token):
        with self.db:
            self.db.execute(
                "DELETE FROM auth_sessions WHERE token_hash=?",
                (hashlib.sha256((token or "").encode()).hexdigest(),),
            )
