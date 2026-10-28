import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crops", "0006_crop_simple_automation_and_mvp_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="CropLightingSchedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("name", models.CharField(default="Iluminação recomendada", max_length=100)),
                ("timezone", models.CharField(default="America/Sao_Paulo", max_length=64)),
                ("days_of_week", models.JSONField(default=list, help_text="0=segunda-feira, 6=domingo")),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("enabled", models.BooleanField(default=True)),
                ("crop", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lighting_schedules", to="crops.crop")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_crop_lighting_schedules", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("crop__common_name", "start_time", "created_at")},
        ),
    ]
