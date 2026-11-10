from django.db import migrations

CREATE = """
CREATE TRIGGER review_no_update_delete
BEFORE UPDATE OR DELETE ON registry_evidencereview
FOR EACH ROW EXECUTE FUNCTION registry_evidence_immutable();

CREATE TRIGGER review_no_truncate
BEFORE TRUNCATE ON registry_evidencereview
FOR EACH STATEMENT EXECUTE FUNCTION registry_evidence_immutable();
"""

DROP = """
DROP TRIGGER IF EXISTS review_no_truncate ON registry_evidencereview;
DROP TRIGGER IF EXISTS review_no_update_delete ON registry_evidencereview;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0004_review_queue"),
    ]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]