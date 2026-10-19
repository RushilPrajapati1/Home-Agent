"""Initial schema: transactions, goals, plans, guide_chunks, imports, monthly_summaries, roles.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from homefund_db.models import (
    CATEGORY_SOURCE_VALUES,
    CATEGORY_VALUES,
    DENSE_DIM,
    IMPORT_STATUS_VALUES,
    PLAN_STATUS_VALUES,
    SPARSE_DIM,
    TRANSACTION_SOURCE_VALUES,
    check_in,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ_ONLY_TABLES = ("transactions", "monthly_summaries", "goals", "guide_chunks")
APP_TABLES = ("transactions", "goals", "plans", "guide_chunks", "imports")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(f"""
        CREATE TABLE transactions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL,
            account text NOT NULL,
            posted_on date NOT NULL,
            amount numeric(12,2) NOT NULL,
            merchant text,
            raw_description text,
            category text NOT NULL,
            category_source text NOT NULL,
            is_fixed boolean NOT NULL DEFAULT false,
            source text NOT NULL,
            dedupe_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_transactions_dedupe_hash UNIQUE (dedupe_hash),
            CONSTRAINT ck_transactions_category CHECK ({check_in("category", CATEGORY_VALUES)}),
            CONSTRAINT ck_transactions_category_source
                CHECK ({check_in("category_source", CATEGORY_SOURCE_VALUES)}),
            CONSTRAINT ck_transactions_source
                CHECK ({check_in("source", TRANSACTION_SOURCE_VALUES)})
        )
    """)
    op.execute("CREATE INDEX ix_transactions_user_posted_on ON transactions (user_id, posted_on)")
    op.execute("COMMENT ON COLUMN transactions.amount IS 'Signed: income +, spending -'")
    op.execute("COMMENT ON COLUMN transactions.merchant IS 'Fernet ciphertext'")
    op.execute("COMMENT ON COLUMN transactions.raw_description IS 'Fernet ciphertext'")

    op.execute("""
        CREATE TABLE goals (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL,
            price numeric(12,2) NOT NULL,
            zip text NOT NULL,
            down_pct numeric(7,4) NOT NULL,
            move_in date NOT NULL,
            saved numeric(12,2) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_goals_user_id ON goals (user_id)")
    op.execute("COMMENT ON COLUMN goals.down_pct IS 'Percentage points: 10 means 10%'")

    op.execute(f"""
        CREATE TABLE plans (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            goal_id uuid REFERENCES goals (id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'running',
            cash_needed numeric(12,2),
            monthly_target numeric(12,2),
            on_track boolean,
            projection jsonb NOT NULL DEFAULT '[]'::jsonb,
            cuts jsonb NOT NULL DEFAULT '[]'::jsonb,
            citations jsonb NOT NULL DEFAULT '[]'::jsonb,
            plan_text text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_plans_status CHECK ({check_in("status", PLAN_STATUS_VALUES)})
        )
    """)
    op.execute("CREATE INDEX ix_plans_goal_id ON plans (goal_id)")

    op.execute(f"""
        CREATE TABLE guide_chunks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            parent_id uuid REFERENCES guide_chunks (id) ON DELETE CASCADE,
            content text NOT NULL,
            dense vector({DENSE_DIM}),
            sparse sparsevec({SPARSE_DIM}),
            metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX ix_guide_chunks_dense_hnsw ON guide_chunks "
        "USING hnsw (dense vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX ix_guide_chunks_metadata ON guide_chunks USING gin (metadata)")
    op.execute("CREATE INDEX ix_guide_chunks_parent_id ON guide_chunks (parent_id)")
    op.execute(
        "COMMENT ON COLUMN guide_chunks.metadata IS "
        "'source (cfpb|hud|glossary), document, section, url, tax_year (int)'"
    )

    op.execute(f"""
        CREATE TABLE imports (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'queued',
            filenames jsonb NOT NULL DEFAULT '[]'::jsonb,
            account text,
            rows_parsed integer NOT NULL DEFAULT 0,
            rows_inserted integer NOT NULL DEFAULT 0,
            duplicates_skipped integer NOT NULL DEFAULT 0,
            categorized_by_rule integer NOT NULL DEFAULT 0,
            categorized_by_llm integer NOT NULL DEFAULT 0,
            error text,
            created_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            CONSTRAINT ck_imports_status CHECK ({check_in("status", IMPORT_STATUS_VALUES)})
        )
    """)
    op.execute("CREATE INDEX ix_imports_user_id ON imports (user_id)")

    op.execute("""
        CREATE MATERIALIZED VIEW monthly_summaries AS
        SELECT user_id,
               date_trunc('month', posted_on)::date AS month,
               category,
               sum(amount)::numeric(12,2) AS total,
               count(*)::integer AS count
        FROM transactions
        GROUP BY user_id, date_trunc('month', posted_on)::date, category
        WITH DATA
    """)
    # Unique index so the importer can REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute(
        "CREATE UNIQUE INDEX ux_monthly_summaries ON monthly_summaries (user_id, month, category)"
    )
    op.execute(
        "COMMENT ON MATERIALIZED VIEW monthly_summaries IS "
        "'total is the signed sum of transactions.amount (spending negative)'"
    )

    # Roles. Created NOLOGIN if absent; `python -m homefund_db.roles` sets LOGIN + password.
    for role in ("app_rw", "mcp_ro"):
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END $$
        """)
    op.execute("GRANT USAGE ON SCHEMA public TO app_rw, mcp_ro")
    # LangGraph's Postgres checkpointer creates its own tables as app_rw.
    op.execute("GRANT CREATE ON SCHEMA public TO app_rw")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(APP_TABLES)} TO app_rw")
    # Only the owner can REFRESH a materialized view; the importer refreshes as app_rw.
    op.execute("ALTER MATERIALIZED VIEW monthly_summaries OWNER TO app_rw")
    op.execute(f"GRANT SELECT ON {', '.join(READ_ONLY_TABLES)} TO mcp_ro")


def downgrade() -> None:
    # Roles are cluster-wide and may hold passwords set outside migrations; they are kept.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS monthly_summaries")
    op.execute("DROP TABLE IF EXISTS imports")
    op.execute("DROP TABLE IF EXISTS plans")
    op.execute("DROP TABLE IF EXISTS goals")
    op.execute("DROP TABLE IF EXISTS guide_chunks")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rw') THEN
                REVOKE CREATE ON SCHEMA public FROM app_rw;
                REVOKE USAGE ON SCHEMA public FROM app_rw;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_ro') THEN
                REVOKE USAGE ON SCHEMA public FROM mcp_ro;
            END IF;
        END $$
    """)
    op.execute("DROP EXTENSION IF EXISTS vector")
