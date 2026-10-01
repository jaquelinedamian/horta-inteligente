from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from accounts.models import Address, Organization
from core.models import BaseModel


def validate_automation_overrides(value):
    if not isinstance(value, dict):
        return
    camera = value.get("camera")
    if not isinstance(camera, dict) or "photos_per_day" not in camera:
        return
    photos_per_day = camera["photos_per_day"]
    if isinstance(photos_per_day, bool):
        raise ValidationError("Fotos por dia deve ser um número entre 1 e 4.")
    try:
        numeric_value = int(photos_per_day)
    except (TypeError, ValueError):
        raise ValidationError("Fotos por dia deve ser um número entre 1 e 4.")
    if numeric_value != photos_per_day or not 1 <= numeric_value <= 4:
        raise ValidationError("Fotos por dia deve estar entre 1 e 4.")


class GardenModel(BaseModel):
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    capacity = models.PositiveSmallIntegerField(default=4)
    reservoir_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    photos_per_day = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(1), MaxValueValidator(4)])
    light_hours_per_day = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    irrigation_frequency_count = models.PositiveSmallIntegerField(null=True, blank=True)
    irrigation_frequency_period = models.CharField(max_length=10, choices=(("day", "Dia"), ("week", "Semana")), default="day")
    pump_duration_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    monitoring_interval_minutes = models.PositiveSmallIntegerField(default=60)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Garden(BaseModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planejada"
        WAITING_INSTALLATION = "waiting_installation", "Aguardando instalação"
        INSTALLED = "installed", "Instalada"
        MAINTENANCE = "maintenance", "Em manutenção"
        INACTIVE = "inactive", "Inativa"
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="gardens")
    garden_model = models.ForeignKey(GardenModel, on_delete=models.PROTECT, null=True, blank=True, related_name="gardens")
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80)
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name="gardens")
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    is_active = models.BooleanField(default=True)
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="responsible_gardens")
    subscription = models.ForeignKey("subscriptions.Subscription", on_delete=models.SET_NULL, null=True, blank=True, related_name="gardens")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PLANNED)
    location_name = models.CharField(max_length=120, blank=True)
    position_description = models.CharField(max_length=180, blank=True)
    sunlight = models.CharField(max_length=20, blank=True)
    socket_nearby = models.BooleanField(null=True, blank=True)
    wifi_available = models.BooleanField(null=True, blank=True)
    wifi_quality = models.CharField(max_length=40, blank=True)
    pets = models.BooleanField(null=True, blank=True)
    children = models.BooleanField(null=True, blank=True)
    restrictions = models.TextField(blank=True)
    site_notes = models.TextField(blank=True)
    equipment_model = models.CharField(max_length=120, blank=True)
    installed_at = models.DateTimeField(null=True, blank=True)
    module_capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    reservoir_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    grow_light_type = models.CharField(max_length=120, blank=True)
    pump_model = models.CharField(max_length=120, blank=True)
    controller_model = models.CharField(max_length=120, blank=True)
    technical_status = models.CharField(max_length=80, blank=True)
    primary_technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="primary_gardens")
    last_visit_at = models.DateTimeField(null=True, blank=True)
    next_visit_at = models.DateTimeField(null=True, blank=True)
    operational_notes = models.TextField(blank=True)
    automation_overrides = models.JSONField(
        default=dict, blank=True, validators=[validate_automation_overrides],
        help_text="Exceções locais sobre a configuração padrão da cultura.",
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_garden_code")]

    def __str__(self):
        return self.name


class GardenMember(BaseModel):
    garden = models.ForeignKey(Garden, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="garden_access")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["garden", "user"], name="uniq_garden_user")]


class GardenConfigurationEvent(BaseModel):
    class Origin(models.TextChoices):
        CUSTOMER = "customer", "Cliente"
        TECHNICIAN = "technician", "Técnico"
        ADMIN = "admin", "Admin"
        RESTORE = "restore", "Restauração padrão"

    garden = models.ForeignKey(Garden, on_delete=models.CASCADE, related_name="configuration_events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="garden_configuration_events")
    origin = models.CharField(max_length=20, choices=Origin.choices)
    previous_configuration = models.JSONField(default=dict)
    new_configuration = models.JSONField(default=dict)

    class Meta:
        ordering = ("-created_at",)


class ModuleType(BaseModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    capabilities = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    width_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    depth_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    pot_volume_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    substrate_capacity_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    water_capacity_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    supports_irrigation = models.BooleanField(default=True)
    supports_lighting = models.BooleanField(default=True)
    supports_sensors = models.BooleanField(default=True)
    recommended_crops = models.ManyToManyField("crops.Crop", blank=True, related_name="recommended_module_types")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class GardenModule(BaseModel):
    class Status(models.TextChoices):
        STOCK = "stock", "Em estoque"
        PREPARED = "prepared", "Preparado"
        INSTALLED = "installed", "Instalado"
        MAINTENANCE = "maintenance", "Em manutenção"
        REMOVED = "removed", "Retirado"
        DISCARDED = "discarded", "Descartado"
        RETIRED = "retired", "Desativado"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="garden_modules")
    module_type = models.ForeignKey(ModuleType, on_delete=models.PROTECT, related_name="modules")
    serial_number = models.CharField(max_length=100)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STOCK)
    qr_identifier = models.CharField(max_length=120, blank=True)
    position_label = models.CharField(max_length=100, blank=True)
    pot_volume_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    substrate_capacity_liters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    installed_at = models.DateTimeField(null=True, blank=True)
    last_changed_at = models.DateTimeField(null=True, blank=True)
    next_change_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "serial_number"], name="uniq_org_module_serial")]

    def __str__(self):
        return f"{self.name} ({self.serial_number})"


class ModuleInstallation(BaseModel):
    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, related_name="installations")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="module_installations")
    position_label = models.CharField(max_length=100, blank=True)
    installed_at = models.DateTimeField()
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["module"], condition=Q(removed_at__isnull=True), name="uniq_active_module_install"),
        ]
