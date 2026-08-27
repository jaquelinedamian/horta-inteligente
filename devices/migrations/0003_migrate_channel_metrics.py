from django.db import migrations


def migrate_metrics(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")
    Metric = apps.get_model("devices", "TelemetryMetric")
    for channel in Channel.objects.exclude(metric="").iterator():
        metric, _ = Metric.objects.get_or_create(
            code=channel.metric,
            defaults={"name": channel.name, "default_unit": channel.unit, "data_type": channel.value_type},
        )
        channel.metric_definition = metric
        channel.save(update_fields=["metric_definition"])


class Migration(migrations.Migration):
    dependencies = [("devices", "0002_telemetrymetric_telemetryreading_notes_and_more")]
    operations = [migrations.RunPython(migrate_metrics, migrations.RunPython.noop)]
