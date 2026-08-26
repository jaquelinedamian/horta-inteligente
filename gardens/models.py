from django.conf import settings
from django.db import models
from django.db.models import Q

from accounts.models import Address, Organization
from core.models import BaseModel


class Garden(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="gardens")
    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=80)
    address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name="gardens")
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "code"], name="uniq_org_garden_code")]

    def __str__(self):
        return self.name


class GardenMember(BaseModel):
    garden = models.ForeignKey(Garden, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="garden_access")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["garden", "user"], name="uniq_garden_user")]


class ModuleType(BaseModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    capabilities = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class GardenModule(BaseModel):
    class Status(models.TextChoices):
        STOCK = "stock", "Em estoque"
        INSTALLED = "installed", "Instalado"
        MAINTENANCE = "maintenance", "Em manutenção"
        RETIRED = "retired", "Desativado"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="garden_modules")
    module_type = models.ForeignKey(ModuleType, on_delete=models.PROTECT, related_name="modules")
    serial_number = models.CharField(max_length=100)
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STOCK)

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
