from django.db import migrations, models


def add_initial_guidance(apps, schema_editor):
    Crop = apps.get_model("crops", "Crop")
    values = {
        "alface": ("Substrato fértil, leve e com boa drenagem.", 15, 24),
        "tomilho": ("Substrato leve e seco entre regas, com drenagem excelente.", 18, 26),
        "coentro": ("Substrato fértil e solto, mantendo boa drenagem.", 17, 25),
    }
    for code, (guidance, minimum, maximum) in values.items():
        Crop.objects.filter(code=code).update(
            cultivation_guidance=guidance,
            ideal_temperature_min=minimum,
            ideal_temperature_max=maximum,
        )


class Migration(migrations.Migration):
    dependencies = [("crops", "0008_supported_crop_catalog")]
    operations = [
        migrations.AddField(model_name="crop", name="cultivation_guidance", field=models.CharField(blank=True, max_length=240)),
        migrations.AddField(model_name="crop", name="image_content_type", field=models.CharField(blank=True, editable=False, max_length=40)),
        migrations.AddField(model_name="crop", name="image_data", field=models.BinaryField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="crop", name="image_filename", field=models.CharField(blank=True, editable=False, max_length=180)),
        migrations.RunPython(add_initial_guidance, migrations.RunPython.noop),
    ]
