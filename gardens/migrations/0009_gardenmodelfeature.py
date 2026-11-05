from django.db import migrations, models
import django.db.models.deletion
import uuid


def copy_legacy_features(apps, schema_editor):
    GardenModel = apps.get_model("gardens", "GardenModel")
    Feature = apps.get_model("gardens", "GardenModelFeature")
    for garden_model in GardenModel.objects.all().iterator():
        dimensions = " Ã— ".join(str(value).rstrip("0").rstrip(".") for value in (garden_model.height_cm, garden_model.width_cm, garden_model.depth_cm) if value is not None)
        values = (
            ("Quantidade de mudas", str(garden_model.capacity or ""), "mudas", "bi-flower1"),
            ("Capacidade do reservatÃ³rio", str(garden_model.reservoir_liters or ""), "L", "bi-droplet"),
            ("DimensÃµes", dimensions, "cm", "bi-rulers"),
            ("Quantidade de mÃ³dulos", str(garden_model.module_count or ""), "mÃ³dulos", "bi-boxes"),
        )
        for order, (name, value, unit, icon) in enumerate(values):
            if value:
                Feature.objects.create(garden_model=garden_model, name=name, value=value, unit=unit, icon=icon, display_order=order)


class Migration(migrations.Migration):
    dependencies = [("gardens", "0008_gardenmodel_images")]
    operations = [
        migrations.CreateModel(
            name="GardenModelFeature",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(max_length=100)), ("value", models.CharField(max_length=180)),
                ("unit", models.CharField(blank=True, max_length=40)),
                ("icon", models.CharField(choices=[("bi-flower1", "Plantas"), ("bi-droplet", "ReservatÃ³rio"), ("bi-rulers", "DimensÃµes"), ("bi-boxes", "MÃ³dulos"), ("bi-arrows-vertical", "Altura"), ("bi-arrows", "Largura"), ("bi-box", "Profundidade"), ("bi-speedometer2", "Peso"), ("bi-lightbulb", "IluminaÃ§Ã£o"), ("bi-camera", "CÃ¢mera"), ("bi-water", "IrrigaÃ§Ã£o"), ("bi-info-circle", "InformaÃ§Ã£o")], default="bi-info-circle", max_length=40)),
                ("display_order", models.PositiveSmallIntegerField(default=0)), ("is_visible", models.BooleanField(default=True)),
                ("garden_model", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="physical_features", to="gardens.gardenmodel")),
            ], options={"ordering": ("display_order", "created_at")},
        ),
        migrations.RunPython(copy_legacy_features, migrations.RunPython.noop),
    ]
