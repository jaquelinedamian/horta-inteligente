from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0006_plan_garden_model")]
    operations = [
        migrations.AddField(model_name="plan", name="image_data", field=models.BinaryField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name="plan", name="image_content_type", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="plan", name="image_filename", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="planentitlement", name="icon", field=models.CharField(blank=True, max_length=50)),
        migrations.AddField(model_name="planentitlement", name="is_included", field=models.BooleanField(default=True)),
    ]
