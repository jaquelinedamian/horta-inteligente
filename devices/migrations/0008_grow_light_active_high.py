from django.db import migrations


def set_grow_light_active_high(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")
    for channel in Channel.objects.filter(metric="light_state", pin="D6").iterator():
        configuration = dict(channel.configuration or {})
        configuration["active_low"] = False
        channel.configuration = configuration
        channel.save(update_fields=["configuration", "updated_at"])


def restore_grow_light_active_low(apps, schema_editor):
    Channel = apps.get_model("devices", "Channel")
    for channel in Channel.objects.filter(metric="light_state", pin="D6").iterator():
        configuration = dict(channel.configuration or {})
        configuration["active_low"] = True
        channel.configuration = configuration
        channel.save(update_fields=["configuration", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("devices", "0007_irrigationschedule_and_controller_channels")]

    operations = [migrations.RunPython(set_grow_light_active_high, restore_grow_light_active_low)]
