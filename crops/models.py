from django.conf import settings
from django.db import models

from core.models import BaseModel
from gardens.models import GardenModule


class Crop(BaseModel):
    common_name = models.CharField(max_length=120)
    scientific_name = models.CharField(max_length=180, blank=True)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    difficulty = models.CharField(max_length=30, default="Fácil")
    light_requirement = models.CharField(max_length=80, blank=True)
    uses = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)

    def __str__(self):
        return self.common_name


class Cultivar(BaseModel):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="cultivars")
    name = models.CharField(max_length=120)
    days_to_harvest = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["crop", "name"], name="uniq_crop_cultivar")]

    def __str__(self):
        return f"{self.crop.common_name} — {self.name}"


class CropRequirement(BaseModel):
    cultivar = models.ForeignKey(Cultivar, on_delete=models.CASCADE, related_name="requirements")
    metric = models.CharField(max_length=50)
    unit = models.CharField(max_length=24)
    minimum = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    maximum = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    target = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cultivar", "metric"], name="uniq_cultivar_metric")]


class PlantingCycle(BaseModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planejado"
        ACTIVE = "active", "Ativo"
        HARVESTED = "harvested", "Colhido"
        CANCELED = "canceled", "Cancelado"

    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, related_name="planting_cycles")
    cultivar = models.ForeignKey(Cultivar, on_delete=models.PROTECT, related_name="planting_cycles")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED)
    planted_at = models.DateTimeField(null=True, blank=True)
    expected_harvest_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)


class CropObservation(BaseModel):
    cycle = models.ForeignKey(PlantingCycle, on_delete=models.CASCADE, related_name="observations")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="crop_observations")
    category = models.CharField(max_length=40, blank=True)
    notes = models.TextField()
    observed_at = models.DateTimeField()


class Harvest(BaseModel):
    cycle = models.ForeignKey(PlantingCycle, on_delete=models.PROTECT, related_name="harvests")
    harvested_at = models.DateTimeField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=20)
    loss_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    quality_notes = models.TextField(blank=True)
