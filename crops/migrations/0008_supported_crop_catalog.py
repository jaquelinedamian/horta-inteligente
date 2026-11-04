from django.db import migrations, models


SUPPORTED_CROPS = {
    "alface": {
        "common_name": "Alface",
        "scientific_name": "Lactuca sativa",
        "soil_moisture_requirement": "Moderada a alta",
        "light_hours": 13,
        "light_requirement": "12–14 horas por dia",
        "water_requirement": "Maior",
        "drainage_requirement": "Boa",
    },
    "tomilho": {
        "common_name": "Tomilho",
        "scientific_name": "Thymus vulgaris",
        "soil_moisture_requirement": "Baixa a moderada",
        "light_hours": 13,
        "light_requirement": "12–14 horas por dia",
        "water_requirement": "Menor; sensível ao excesso de umidade",
        "drainage_requirement": "Excelente",
    },
    "coentro": {
        "common_name": "Coentro",
        "scientific_name": "Coriandrum sativum",
        "soil_moisture_requirement": "Moderada",
        "light_hours": 13,
        "light_requirement": "12–14 horas por dia",
        "water_requirement": "Moderada",
        "drainage_requirement": "Boa",
    },
}


def configure_supported_crops(apps, schema_editor):
    Crop = apps.get_model("crops", "Crop")
    selected_ids = []
    for code, defaults in SUPPORTED_CROPS.items():
        crop, _ = Crop.objects.update_or_create(code=code, defaults={**defaults, "is_available": True})
        selected_ids.append(crop.pk)
    # Mantém registros e relacionamentos históricos; somente os remove dos novos seletores.
    Crop.objects.exclude(pk__in=selected_ids).update(is_available=False)


class Migration(migrations.Migration):
    dependencies = [("crops", "0007_croplightingschedule")]
    operations = [
        migrations.AddField(model_name="crop", name="soil_moisture_requirement", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="crop", name="water_requirement", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="crop", name="drainage_requirement", field=models.CharField(blank=True, max_length=80)),
        migrations.RunPython(configure_supported_crops, migrations.RunPython.noop),
    ]
