from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gardens", "0006_limit_photos_per_day")]
    operations = [
        migrations.AddField(model_name="gardenmodel", name="height_cm", field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
        migrations.AddField(model_name="gardenmodel", name="width_cm", field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
        migrations.AddField(model_name="gardenmodel", name="depth_cm", field=models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
        migrations.AddField(model_name="gardenmodel", name="module_count", field=models.PositiveSmallIntegerField(blank=True, null=True)),
    ]
