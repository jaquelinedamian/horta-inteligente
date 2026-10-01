from django.db import migrations, models
from django.utils.text import slugify


MVP_CROPS = (("salsinha", "Salsinha"), ("cebolinha", "Cebolinha"), ("coentro", "Coentro"), ("oregano", "Orégano"))


def seed_mvp_crops(apps, schema_editor):
    Crop = apps.get_model("crops", "Crop")
    selected_ids = []
    for code, name in MVP_CROPS:
        crop = Crop.objects.filter(code=code).first()
        if not crop:
            crop = next((item for item in Crop.objects.all() if slugify(item.common_name) == code), None)
        if crop:
            changed = []
            if crop.code != code and not Crop.objects.filter(code=code).exclude(pk=crop.pk).exists():
                crop.code = code; changed.append("code")
            if not crop.is_available:
                crop.is_available = True; changed.append("is_available")
            if changed: crop.save(update_fields=changed)
        else:
            crop = Crop.objects.create(common_name=name, code=code, is_available=True)
        selected_ids.append(crop.pk)
    Crop.objects.exclude(pk__in=selected_ids).update(is_available=False)


class Migration(migrations.Migration):
    dependencies = [("crops", "0005_cropcultivationprofile_automation_config")]
    operations = [
        migrations.AddField(model_name="crop", name="irrigation_frequency_count", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="crop", name="irrigation_frequency_period", field=models.CharField(choices=[("day", "Dia"), ("week", "Semana")], default="day", max_length=10)),
        migrations.AddField(model_name="crop", name="pump_duration_seconds", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.RunPython(seed_mvp_crops, migrations.RunPython.noop),
    ]
