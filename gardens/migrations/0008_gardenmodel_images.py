from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gardens", "0007_gardenmodel_dimensions")]
    operations = [
        migrations.AddField(model_name="gardenmodel", name="image_data", field=models.BinaryField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="gardenmodel", name="image_content_type", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="gardenmodel", name="image_filename", field=models.CharField(blank=True, max_length=180)),
    ]
