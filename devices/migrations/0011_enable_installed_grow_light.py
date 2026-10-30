from django.db import migrations


def enable_installed_grow_light(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")
    channels = Channel.objects.filter(
        device__kind="esp8266",
        key="grow-light",
        metric="light_state",
        pin="D6",
    )
    for channel in channels.iterator():
        configuration = dict(channel.configuration or {})
        configuration.update({"component": "relay_2ch", "active_low": False})
        channel.configuration = configuration
        channel.is_enabled = True
        channel.save(update_fields=["configuration", "is_enabled", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("devices", "0010_disable_uninstalled_grow_light")]

    operations = [
        migrations.RunPython(enable_installed_grow_light, migrations.RunPython.noop),
    ]
