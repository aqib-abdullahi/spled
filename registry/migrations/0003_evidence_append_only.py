from django.db import migrations

CREATE = """
CREATE FUNCTION registry_evidence_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Evidence is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER evidence_no_update_delete
BEFORE UPDATE OR DELETE ON registry_evidenceentry
FOR EACH ROW EXECUTE FUNCTION registry_evidence_immutable();

CREATE TRIGGER evidence_no_truncate
BEFORE TRUNCATE ON registry_evidenceentry
FOR EACH STATEMENT EXECUTE FUNCTION registry_evidence_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS evidence_no_truncate ON registry_evidenceentry;
DROP TRIGGER IF EXISTS evidence_no_update_delete ON registry_evidenceentry;
DROP FUNCTION IF EXISTS registry_evidence_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0002_evidenceentry"),
    ]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]