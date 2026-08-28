from django.db.models import Prefetch
from devices.models import Device
from crops.models import PlantingCycle

from .models import Garden, GardenModule, ModuleInstallation


def get_active_module_installation(module):
    return module.installations.filter(removed_at__isnull=True).select_related("garden").first()


def get_installed_modules(garden):
    return GardenModule.objects.filter(installations__garden=garden, installations__removed_at__isnull=True).select_related("module_type").distinct()


def get_active_installations(organization):
    return ModuleInstallation.objects.filter(module__organization=organization, garden__organization=organization, removed_at__isnull=True)


def get_customer_gardens(organization):
    active_cycles = PlantingCycle.objects.filter(status=PlantingCycle.Status.ACTIVE).select_related("crop", "cultivar__crop")
    return Garden.objects.filter(organization=organization, is_active=True).select_related("subscription", "address").prefetch_related("module_installations__module__module_type", Prefetch("module_installations__module__planting_cycles", queryset=active_cycles, to_attr="active_cycles"))


def get_customer_modules(organization):
    return GardenModule.objects.filter(organization=organization).select_related("module_type").prefetch_related("installations")


def get_customer_devices(organization):
    return Device.objects.filter(organization=organization).select_related("model", "module").prefetch_related("channels")
