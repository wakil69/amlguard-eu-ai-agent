"""Add tenant and investigator assignment to cases."""

from alembic import op

revision = "0002_case_tenant_assignment"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE casework.cases "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE casework.cases "
        "ADD COLUMN IF NOT EXISTS assigned_investigator_id VARCHAR(120)"
    )
    op.execute(
        "UPDATE casework.cases SET tenant_id = 'legacy-unassigned' "
        "WHERE tenant_id IS NULL"
    )
    op.execute(
        "UPDATE casework.cases SET assigned_investigator_id = 'legacy-unassigned' "
        "WHERE assigned_investigator_id IS NULL"
    )
    op.execute("ALTER TABLE casework.cases ALTER COLUMN tenant_id SET NOT NULL")
    op.execute(
        "ALTER TABLE casework.cases "
        "ALTER COLUMN assigned_investigator_id SET NOT NULL"
    )
    op.execute("ALTER TABLE casework.cases DROP CONSTRAINT IF EXISTS cases_alert_id_key")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_cases_tenant_alert'
            ) THEN
                ALTER TABLE casework.cases
                ADD CONSTRAINT uq_cases_tenant_alert UNIQUE (tenant_id, alert_id);
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_casework_cases_tenant_id "
        "ON casework.cases (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_casework_cases_assigned_investigator_id "
        "ON casework.cases (assigned_investigator_id)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE casework.cases "
        "DROP CONSTRAINT IF EXISTS uq_cases_tenant_alert"
    )
    op.execute("DROP INDEX IF EXISTS casework.ix_casework_cases_tenant_id")
    op.execute(
        "DROP INDEX IF EXISTS casework.ix_casework_cases_assigned_investigator_id"
    )
    op.execute(
        "ALTER TABLE casework.cases "
        "DROP COLUMN IF EXISTS assigned_investigator_id"
    )
    op.execute("ALTER TABLE casework.cases DROP COLUMN IF EXISTS tenant_id")
    op.create_unique_constraint(
        "cases_alert_id_key",
        "cases",
        ["alert_id"],
        schema="casework",
    )
