from django.db import migrations, models
import django.db.models.deletion
import uuid


DEFAULT_CHANNELS = (
    {"key": "soil-moisture", "name": "Umidade do solo", "kind": "sensor", "metric": "soil_moisture", "unit": "%", "value_type": "decimal", "pin": "A0", "configuration": {"component": "analog_soil_sensor", "dry_raw": 850, "wet_raw": 350}, "is_enabled": True},
    {"key": "grow-light", "name": "Iluminação", "kind": "actuator", "metric": "light_state", "unit": "", "value_type": "boolean", "pin": "D6", "configuration": {"component": "relay_2ch", "active_low": True}, "is_enabled": True},
)


def add_channels(apps, schema_editor):
    Device = apps.get_model("devices", "Device")
    Channel = apps.get_model("devices", "Channel")
    for device in Device.objects.filter(kind="esp8266").iterator():
        for definition in DEFAULT_CHANNELS:
            Channel.objects.get_or_create(device_id=device.id, key=definition["key"], defaults=definition)


class Migration(migrations.Migration):
    dependencies = [("devices", "0006_provision_controller_default_channels")]
    operations = [
        migrations.CreateModel(
            name="IrrigationSchedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(default="Irrigação", max_length=100)),
                ("timezone", models.CharField(default="America/Sao_Paulo", max_length=64)),
                ("days_of_week", models.JSONField(default=list, help_text="0=segunda-feira, 6=domingo")),
                ("start_time", models.TimeField()),
                ("duration_seconds", models.PositiveSmallIntegerField(default=10)),
                ("enabled", models.BooleanField(default=True)),
                ("actuator", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="irrigation_schedules", to="devices.channel")),
            ],
        ),
        migrations.RunPython(add_channels, migrations.RunPython.noop),
    ]
