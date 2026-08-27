from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

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
    botanical_family = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=20, blank=True)
    origin = models.CharField(max_length=120, blank=True)
    life_cycle = models.CharField(max_length=20, blank=True)
    edible_part = models.CharField(max_length=100, blank=True)
    page_title = models.CharField(max_length=180, blank=True)
    short_description = models.CharField(max_length=300, blank=True)
    flavor = models.CharField(max_length=160, blank=True)
    aroma = models.CharField(max_length=160, blank=True)
    is_featured = models.BooleanField(default=False)
    image_url = models.URLField(blank=True)
    minimum_temperature = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ideal_temperature_min = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ideal_temperature_max = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    maximum_temperature = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    minimum_humidity = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    maximum_humidity = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    light_hours = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    target_ppfd = models.PositiveIntegerField(null=True, blank=True)
    root_depth_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    minimum_pot_liters = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    allows_regrowth = models.BooleanField(default=False)
    estimated_harvests = models.PositiveSmallIntegerField(default=1)
    cut_interval_days = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        return self.common_name


class Cultivar(BaseModel):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="cultivars")
    name = models.CharField(max_length=120)
    days_to_harvest = models.PositiveSmallIntegerField(null=True, blank=True)
    code = models.SlugField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    size = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=80, blank=True)
    flavor = models.CharField(max_length=120, blank=True)
    vigor = models.CharField(max_length=120, blank=True)
    resistance = models.TextField(blank=True)
    specific_characteristics = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

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
    organization = models.ForeignKey("accounts.Organization", on_delete=models.PROTECT, null=True, blank=True, related_name="planting_cycles")
    garden = models.ForeignKey("gardens.Garden", on_delete=models.PROTECT, null=True, blank=True, related_name="planting_cycles")
    crop = models.ForeignKey(Crop, on_delete=models.PROTECT, null=True, blank=True, related_name="planting_cycles")
    cultivation_profile = models.ForeignKey("CropCultivationProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="planting_cycles")
    substrate_recipe = models.ForeignKey("SubstrateRecipe", on_delete=models.SET_NULL, null=True, blank=True, related_name="planting_cycles")
    nutrition_plan = models.ForeignKey("CropNutritionPlan", on_delete=models.SET_NULL, null=True, blank=True, related_name="planting_cycles")
    origin = models.CharField(max_length=20, choices=(("seed", "Semente"), ("seedling", "Muda"), ("cutting", "Estaca")), blank=True)
    batch_code = models.CharField(max_length=80, blank=True)
    current_stage = models.ForeignKey("CropStageProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="active_cycles")
    expected_end_at = models.DateTimeField(null=True, blank=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="responsible_cycles")
    closure_reason = models.TextField(blank=True)
    maximum_cuts = models.PositiveSmallIntegerField(null=True, blank=True)
    cuts_completed = models.PositiveSmallIntegerField(default=0)
    next_harvest_at = models.DateTimeField(null=True, blank=True)


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


class CropCultivationProfile(BaseModel):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="cultivation_profiles")
    cultivar = models.ForeignKey(Cultivar, on_delete=models.CASCADE, null=True, blank=True, related_name="cultivation_profiles")
    cultivation_system = models.CharField(max_length=30, choices=(("substrate", "Vaso com substrato"), ("soil", "Solo"), ("hydroponics", "Hidroponia")))
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    target_temperature_min = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    target_temperature_max = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    target_humidity_min = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    target_humidity_max = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    photoperiod_hours = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    target_ppfd = models.PositiveIntegerField(null=True, blank=True)
    substrate_moisture_min = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    substrate_moisture_max = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    initial_irrigation_amount = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    irrigation_unit = models.CharField(max_length=20, blank=True)
    initial_irrigation_interval_hours = models.PositiveIntegerField(null=True, blank=True)
    ph_min = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ph_target = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ph_max = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ec_min = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    ec_target = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    ec_max = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    def __str__(self): return f"{self.crop.common_name} — {self.name}"


class CropStageProfile(BaseModel):
    profile = models.ForeignKey(CropCultivationProfile, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=100)
    position = models.PositiveSmallIntegerField(default=0)
    estimated_duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    temperature = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    humidity = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    photoperiod_hours = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    ppfd = models.PositiveIntegerField(null=True, blank=True)
    substrate_moisture = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    irrigation_notes = models.TextField(blank=True)
    ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ec = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    fertilization_notes = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    class Meta: ordering = ("profile", "position")
    def __str__(self): return f"{self.profile} — {self.name}"


class SubstrateMaterial(BaseModel):
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=80, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    supplier = models.ForeignKey("operations.Supplier", on_delete=models.SET_NULL, null=True, blank=True, related_name="substrate_materials")
    description = models.TextField(blank=True)
    organic_matter_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    ec = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    density = models.DecimalField(max_digits=9, decimal_places=3, null=True, blank=True)
    water_retention_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    aeration_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    porosity_percent = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    particle_size = models.CharField(max_length=80, blank=True)
    stock_unit = models.CharField(max_length=20, default="L")
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name


class SubstrateRecipe(BaseModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80)
    version = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True)
    intended_use = models.TextField(blank=True)
    target_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    target_ec = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    class Meta: constraints = [models.UniqueConstraint(fields=["code", "version"], name="uniq_substrate_recipe_version")]
    def __str__(self): return f"{self.name} v{self.version}"


class SubstrateRecipeComponent(BaseModel):
    recipe = models.ForeignKey(SubstrateRecipe, on_delete=models.CASCADE, related_name="components")
    material = models.ForeignKey(SubstrateMaterial, on_delete=models.PROTECT, related_name="recipe_components")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    def clean(self):
        if self.percentage is not None and self.recipe_id:
            total = self.recipe.components.exclude(pk=self.pk).aggregate(total=models.Sum("percentage"))["total"] or 0
            if total + self.percentage > 100: raise ValidationError("A soma dos componentes não pode ultrapassar 100%.")


class Fertilizer(BaseModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    supplier = models.ForeignKey("operations.Supplier", on_delete=models.SET_NULL, null=True, blank=True, related_name="fertilizers")
    kind = models.CharField(max_length=20, choices=(("mineral", "Mineral"), ("organic", "Orgânico"), ("organomineral", "Organomineral")))
    form = models.CharField(max_length=20, choices=(("liquid", "Líquido"), ("powder", "Pó"), ("granular", "Granular")))
    nitrogen = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    phosphorus = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    potassium = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    micronutrients = models.JSONField(default=dict, blank=True)
    unit = models.CharField(max_length=20, default="ml")
    recommended_dilution = models.CharField(max_length=120, blank=True)
    application_method = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    def __str__(self): return self.name


class CropNutritionPlan(BaseModel):
    crop = models.ForeignKey(Crop, on_delete=models.CASCADE, related_name="nutrition_plans")
    cultivar = models.ForeignKey(Cultivar, on_delete=models.CASCADE, null=True, blank=True, related_name="nutrition_plans")
    cultivation_profile = models.ForeignKey(CropCultivationProfile, on_delete=models.CASCADE, null=True, blank=True, related_name="nutrition_plans")
    stage = models.ForeignKey(CropStageProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="nutrition_plans")
    fertilizer = models.ForeignKey(Fertilizer, on_delete=models.PROTECT, related_name="nutrition_plans")
    dose = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.CharField(max_length=30)
    dilution_volume = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    frequency_days = models.PositiveSmallIntegerField(null=True, blank=True)
    method = models.CharField(max_length=100, blank=True)
    target_ec = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    target_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    def __str__(self): return f"{self.crop.common_name} — {self.fertilizer.name}"


class HarvestEvent(BaseModel):
    cycle = models.ForeignKey(PlantingCycle, on_delete=models.PROTECT, related_name="harvest_events")
    harvest_number = models.PositiveSmallIntegerField()
    harvested_at = models.DateTimeField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=20)
    quality = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    class Meta: constraints = [models.UniqueConstraint(fields=["cycle", "harvest_number"], name="uniq_cycle_harvest_number")]
