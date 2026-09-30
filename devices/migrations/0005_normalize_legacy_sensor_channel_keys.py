from django.db import migrations


LEGACY_SENSOR_KEYS = (
    ("temperature", "air-temperature", "air_temperature"),
    ("pressure", "air-pressure", "air_pressure"),
)


def normalize_legacy_sensor_channel_keys(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")

    for legacy_key, canonical_key, metric in LEGACY_SENSOR_KEYS:
        legacy_channels = Channel.objects.filter(
            key=legacy_key,
            kind="sensor",
            metric=metric,
        ).iterator()

        for channel in legacy_channels:
            canonical_exists = Channel.objects.filter(
                device_id=channel.device_id,
                key=canonical_key,
            ).exists()
            if not canonical_exists:
                channel.key = canonical_key
                channel.save(update_fields=["key"])


class Migration(migrations.Migration):
    dependencies = [("devices", "0004_device_garden_device_kind_device_local_ip_and_more")]
    operations = [
        migrations.RunPython(
            normalize_legacy_sensor_channel_keys,
            migrations.RunPython.noop,
        ),
    ]
