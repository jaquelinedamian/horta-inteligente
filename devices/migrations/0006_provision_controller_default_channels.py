from django.db import migrations


DEFAULT_CHANNELS = (
    {
        "key": "air-temperature", "name": "Temperatura do ar", "kind": "sensor",
        "metric": "air_temperature", "unit": "°C", "value_type": "decimal", "pin": "I2C",
        "configuration": {"component": "BMP280"}, "is_enabled": True,
    },
    {
        "key": "air-pressure", "name": "Pressão atmosférica", "kind": "sensor",
        "metric": "air_pressure", "unit": "hPa", "value_type": "decimal", "pin": "I2C",
        "configuration": {"component": "BMP280"}, "is_enabled": True,
    },
    {
        "key": "pump", "name": "Bomba", "kind": "actuator",
        "metric": "pump_state", "unit": "", "value_type": "boolean", "pin": "D5",
        "configuration": {"component": "relay_1ch", "active_low": True}, "is_enabled": True,
    },
)


def provision_controller_default_channels(apps, schema_editor):
    Device = apps.get_model("devices", "Device")
    Channel = apps.get_model("devices", "Channel")
    database = schema_editor.connection.alias
    controllers = Device.objects.using(database).filter(kind="esp8266").iterator()
    for device in controllers:
        for definition in DEFAULT_CHANNELS:
            Channel.objects.using(database).get_or_create(
                device_id=device.id,
                key=definition["key"],
                defaults=definition,
            )


class Migration(migrations.Migration):
    dependencies = [("devices", "0005_normalize_legacy_sensor_channel_keys")]
    operations = [
        migrations.RunPython(provision_controller_default_channels, migrations.RunPython.noop),
    ]
