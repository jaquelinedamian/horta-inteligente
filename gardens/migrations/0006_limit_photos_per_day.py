from django.db import migrations, models
import django.core.validators
import gardens.models


def limit_legacy_photo_frequency(apps, schema_editor):
    GardenModel = apps.get_model("gardens", "GardenModel")
    Garden = apps.get_model("gardens", "Garden")

    GardenModel.objects.filter(photos_per_day__gt=4).update(photos_per_day=4)
    GardenModel.objects.filter(photos_per_day__lt=1).update(photos_per_day=1)

    for garden in Garden.objects.all().only("pk", "automation_overrides").iterator():
        overrides = garden.automation_overrides
        if not isinstance(overrides, dict):
            continue
        camera = overrides.get("camera")
        if not isinstance(camera, dict) or "photos_per_day" not in camera:
            continue
        value = camera.get("photos_per_day")
        if isinstance(value, bool):
            safe_value = 4
        else:
            try:
                safe_value = max(1, min(int(value), 4))
            except (TypeError, ValueError, OverflowError):
                safe_value = 4
        if value != safe_value:
            updated = dict(overrides)
            updated["camera"] = {**camera, "photos_per_day": safe_value}
            Garden.objects.filter(pk=garden.pk).update(automation_overrides=updated)


class Migration(migrations.Migration):
    dependencies = [("gardens", "0005_garden_configuration_defaults_and_events")]

    operations = [
        migrations.RunPython(limit_legacy_photo_frequency, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="gardenmodel",
            name="photos_per_day",
            field=models.PositiveSmallIntegerField(
                default=4,
                validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(4)],
            ),
        ),
        migrations.AlterField(
            model_name="garden",
            name="automation_overrides",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Exceções locais sobre a configuração padrão da cultura.",
                validators=[gardens.models.validate_automation_overrides],
            ),
        ),
    ]
