from devices.models import Device

from .models import Garden, GardenModule


def get_customer_gardens(organization):
    return Garden.objects.filter(organization=organization, is_active=True).select_related("subscription", "address").prefetch_related("module_installations__module")


def get_customer_modules(organization):
    return GardenModule.objects.filter(organization=organization).select_related("module_type").prefetch_related("installations")


def get_customer_devices(organization):
    return Device.objects.filter(organization=organization).select_related("model", "module").prefetch_related("channels")
