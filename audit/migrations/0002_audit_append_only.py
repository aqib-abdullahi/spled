from django.db import migrations

CREATE = """
CREATE TRIGGER audit_no_update_delete
BEFORE UPDATE OR DELETE ON audit_auditevent
FOR EACH ROW EXECUTE FUNCTION registry_evidence_immutable();

CREATE TRIGGER audit_no_truncate
BEFORE TRUNCATE ON audit_auditevent
FOR EACH STATEMENT EXECUTE FUNCTION registry_evidence_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS audit_no_truncate ON audit_auditevent;
DROP TRIGGER IF EXISTS audit_no_update_delete ON audit_auditevent;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("registry", "0003_evidence_append_only"),
    ]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]