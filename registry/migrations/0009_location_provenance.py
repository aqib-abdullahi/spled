from django.db import migrations, models


class Migration(migrations.Migration):
    # Adds three columns. Existing rows get blank/empty values; nothing is updated, so the
    # append-only triggers on registry_evidenceentry are never involved.
    dependencies = [
        ("registry", "0008_site_progress_from_milestones_milestone"),
    ]

    operations = [
        migrations.AddField(
            model_name="evidenceentry",
            name="location_source",
            field=models.CharField(blank=True, default="", editable=False, max_length=20),
        ),
        migrations.AddField(
            model_name="evidenceentry",
            name="location_accuracy_m",
            field=models.FloatField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="evidenceentry",
            name="location_fixed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]