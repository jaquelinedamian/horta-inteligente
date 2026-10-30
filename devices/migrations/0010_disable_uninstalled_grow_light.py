from django.db import migrations


def mark_grow_light_uninstalled(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")
    for channel in Channel.objects.filter(metric="light_state", pin="D6").iterator():
        configuration = dict(channel.configuration or {})
        configuration["active_low"] = True
        channel.configuration = configuration
        channel.is_enabled = False
        channel.save(update_fields=["configuration", "is_enabled", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("devices", "0009_gardenphoto_source")]

    operations = [migrations.RunPython(mark_grow_light_uninstalled, migrations.RunPython.noop)]
