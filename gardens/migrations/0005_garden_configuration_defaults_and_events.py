import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("gardens", "0004_gardenmodel_garden_garden_model"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="gardenmodel", name="light_hours_per_day", field=models.DecimalField(blank=True, decimal_places=1, max_digits=4, null=True)),
        migrations.AddField(model_name="gardenmodel", name="irrigation_frequency_count", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="gardenmodel", name="irrigation_frequency_period", field=models.CharField(choices=[("day", "Dia"), ("week", "Semana")], default="day", max_length=10)),
        migrations.AddField(model_name="gardenmodel", name="pump_duration_seconds", field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="gardenmodel", name="monitoring_interval_minutes", field=models.PositiveSmallIntegerField(default=60)),
        migrations.CreateModel(
            name="GardenConfigurationEvent",
            fields=[
                ("id", models.UUIDField(default=__import__('uuid').uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("origin", models.CharField(choices=[("customer", "Cliente"), ("technician", "Técnico"), ("admin", "Admin"), ("restore", "Restauração padrão")], max_length=20)),
                ("previous_configuration", models.JSONField(default=dict)),
                ("new_configuration", models.JSONField(default=dict)),
                ("garden", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="configuration_events", to="gardens.garden")),
                ("user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="garden_configuration_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
