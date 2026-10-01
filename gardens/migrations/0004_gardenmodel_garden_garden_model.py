from django.db import migrations, models
import django.db.models.deletion
import uuid


def assign_compatible_models(apps, schema_editor):
    GardenModel = apps.get_model("gardens", "GardenModel")
    Garden = apps.get_model("gardens", "Garden")
    fallback, _ = GardenModel.objects.get_or_create(
        code="hortaviva-legado",
        defaults={"name": "HortaViva (modelo legado)", "description": "Modelo criado para hortas anteriores à simplificação.", "capacity": 4, "photos_per_day": 4, "is_active": False},
    )
    Garden.objects.filter(garden_model__isnull=True).update(garden_model=fallback)


class Migration(migrations.Migration):
    dependencies = [("gardens", "0003_garden_automation_overrides")]
    operations = [
        migrations.CreateModel(
            name="GardenModel",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=120)), ("code", models.SlugField(max_length=80, unique=True)),
                ("description", models.TextField(blank=True)), ("capacity", models.PositiveSmallIntegerField(default=4)),
                ("reservoir_liters", models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ("photos_per_day", models.PositiveSmallIntegerField(default=4)), ("is_active", models.BooleanField(default=True)),
            ], options={"abstract": False},
        ),
        migrations.AddField(model_name="garden", name="garden_model", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="gardens", to="gardens.gardenmodel")),
        migrations.RunPython(assign_compatible_models, migrations.RunPython.noop),
    ]
