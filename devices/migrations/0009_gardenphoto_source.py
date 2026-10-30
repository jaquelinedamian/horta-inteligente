from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("devices", "0008_grow_light_active_high")]

    operations = [
        migrations.AddField(
            model_name="gardenphoto",
            name="source",
            field=models.CharField(
                choices=[("automatic", "Automática"), ("manual", "Manual")],
                default="automatic",
                max_length=16,
            ),
        ),
    ]
