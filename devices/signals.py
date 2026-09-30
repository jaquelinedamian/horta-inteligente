from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Device
from .services import ensure_controller_default_channels


@receiver(post_save, sender=Device)
def provision_controller_channels(sender, instance, created, **kwargs):
    if created:
        ensure_controller_default_channels(instance)
