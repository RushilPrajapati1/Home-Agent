"""Give app_rw and mcp_ro LOGIN and their passwords from the environment.

Migration 0001 creates both roles NOLOGIN; `make migrate` runs this right after it.
Idempotent, so it is safe to run on every migrate.
"""

from __future__ import annotations

import os

from sqlalchemy import text

from homefund_db.config import ADMIN_URL_VAR, make_engine

ROLE_PASSWORD_VARS = {"app_rw": "APP_RW_PASSWORD", "mcp_ro": "MCP_RO_PASSWORD"}


def main() -> None:
    engine = make_engine(ADMIN_URL_VAR)
    with engine.begin() as conn:
        for role, var in ROLE_PASSWORD_VARS.items():
            password = os.environ.get(var, "")
            if not password:
                raise SystemExit(f"{var} is not set; copy .env.example to .env")
            # ALTER ROLE cannot take bind parameters; quote_literal escapes the value.
            quoted = conn.execute(text("SELECT quote_literal(:p)"), {"p": password}).scalar_one()
            conn.execute(text(f"ALTER ROLE {role} WITH LOGIN PASSWORD {quoted}"))
            print(f"role {role}: login enabled")


if __name__ == "__main__":
    main()
