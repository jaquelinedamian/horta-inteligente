from django.db.models import Case, IntegerField, Value, When

from .models import Crop, Cultivar, PlantingCycle


SUPPORTED_CROP_CODES = ("alface", "tomilho", "coentro")


def _supported_crop_order():
    return Case(
        *(When(code=code, then=Value(position)) for position, code in enumerate(SUPPORTED_CROP_CODES)),
        output_field=IntegerField(),
    )


def get_available_crops():
    """Single source of truth for crops offered in new customer journeys."""
    return Crop.objects.filter(is_available=True, code__in=SUPPORTED_CROP_CODES).order_by(
        _supported_crop_order(), "common_name"
    )


def get_public_crops():
    """Compatibility alias for public pages."""
    return get_available_crops().prefetch_related("cultivars")


def get_available_cultivars(crop=None):
    queryset = Cultivar.objects.filter(
        is_active=True, crop__is_available=True, crop__code__in=SUPPORTED_CROP_CODES
    ).select_related("crop")
    return queryset.filter(crop=crop) if crop else queryset


def get_customer_cycles(organization):
    return PlantingCycle.objects.filter(module__organization=organization).select_related("crop", "cultivar__crop", "module", "current_stage")
