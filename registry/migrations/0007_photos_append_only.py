from django.db import migrations

CREATE = """
CREATE TRIGGER photo_no_update_delete
BEFORE UPDATE OR DELETE ON registry_evidencephoto
FOR EACH ROW EXECUTE FUNCTION registry_evidence_immutable();

CREATE TRIGGER photo_no_truncate
BEFORE TRUNCATE ON registry_evidencephoto
FOR EACH STATEMENT EXECUTE FUNCTION registry_evidence_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS photo_no_truncate ON registry_evidencephoto;
DROP TRIGGER IF EXISTS photo_no_update_delete ON registry_evidencephoto;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0006_photos"),
    ]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]