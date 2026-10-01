from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("gardens", "0004_gardenmodel_garden_garden_model"), ("subscriptions", "0005_checkoutrequest_selected_crops")]
    operations = [migrations.AddField(model_name="plan", name="garden_model", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="plans", to="gardens.gardenmodel"))]
