"""Column encryption for merchant and raw description, and the transaction dedupe hash.

Only those two columns are encrypted, so amounts, dates and categories stay summable in
SQL. Ciphertext is a Fernet token (AES-128-CBC + HMAC-SHA256) stored as text.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

ENCRYPTION_KEY_VAR = "COLUMN_ENCRYPTION_KEY"
DEDUPE_KEY_VAR = "DEDUPE_HMAC_KEY"


def _require(var: str) -> str:
    value = os.environ.get(var, "").strip()
    if not value:
        raise RuntimeError(f"{var} is not set; copy .env.example to .env")
    return value


@lru_cache(maxsize=4)
def _fernet(key: str) -> Fernet:
    return Fernet(key.encode())


def encrypt(plaintext: str, key: str | None = None) -> str:
    return _fernet(key or _require(ENCRYPTION_KEY_VAR)).encrypt(plaintext.encode()).decode()


def decrypt(token: str, key: str | None = None) -> str:
    return _fernet(key or _require(ENCRYPTION_KEY_VAR)).decrypt(token.encode()).decode()


class EncryptedText(TypeDecorator[str]):
    """Transparently encrypts on write and decrypts on read. Not searchable or sortable."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        return None if value is None else decrypt(str(value))


def dedupe_hash(
    *,
    user_id: UUID,
    account: str,
    posted_on: date,
    amount: Decimal,
    raw_description: str,
    reference: str | None,
    key: str | None = None,
) -> str:
    """HMAC-SHA256 over the fields that identify one real-world transaction.

    ``reference`` is the bank's id (OFX FITID, CSV reference, Plaid transaction_id). Two
    same-day purchases with equal amounts differ by reference; a row exported twice does
    not. Keyed, so the hash does not leak the encrypted description.
    """
    message = "|".join(
        [
            str(user_id),
            account.strip().lower(),
            posted_on.isoformat(),
            str(amount.quantize(Decimal("0.01"))),
            " ".join(raw_description.split()).upper(),
            (reference or "").strip(),
        ]
    )
    secret = (key or _require(DEDUPE_KEY_VAR)).encode()
    return hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()
