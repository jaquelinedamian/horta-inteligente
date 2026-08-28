from .models import Crop, Cultivar, PlantingCycle


def get_available_crops():
    """Single source of truth for crops offered in new customer journeys."""
    return Crop.objects.filter(is_available=True).order_by("common_name")


def get_public_crops():
    """Compatibility alias for public pages."""
    return get_available_crops().prefetch_related("cultivars")


def get_available_cultivars(crop=None):
    queryset = Cultivar.objects.filter(is_active=True, crop__is_available=True).select_related("crop")
    return queryset.filter(crop=crop) if crop else queryset


def get_customer_cycles(organization):
    return PlantingCycle.objects.filter(module__organization=organization).select_related("crop", "cultivar__crop", "module", "current_stage")
