from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import GardenModule, ModuleInstallation


@transaction.atomic
def install_module(module, garden, installed_at=None, position_label=""):
    if module.organization_id != garden.organization_id:
        raise ValidationError("O módulo e a horta precisam pertencer ao mesmo cliente.")
    installed_at = installed_at or timezone.now()
    ModuleInstallation.objects.select_for_update().filter(module=module, removed_at__isnull=True).update(removed_at=installed_at)
    installation = ModuleInstallation.objects.create(module=module, garden=garden, installed_at=installed_at, position_label=position_label)
    module.status = GardenModule.Status.INSTALLED
    module.installed_at = installed_at
    module.position_label = position_label
    module.last_changed_at = installed_at
    module.save(update_fields=["status", "installed_at", "position_label", "last_changed_at", "updated_at"])
    return installation


@transaction.atomic
def remove_module(module, removed_at=None, new_status=GardenModule.Status.STOCK):
    removed_at = removed_at or timezone.now()
    ModuleInstallation.objects.select_for_update().filter(module=module, removed_at__isnull=True).update(removed_at=removed_at)
    module.status = new_status
    module.last_changed_at = removed_at
    module.save(update_fields=["status", "last_changed_at", "updated_at"])
    return module


@transaction.atomic
def create_customer_module(form, organization):
    module = form.save(commit=False)
    module.organization = organization
    module.status = GardenModule.Status.STOCK
    module.save()
    if form.cleaned_data["placement"] == "install":
        install_module(module, form.cleaned_data["garden"], form.cleaned_data.get("installation_date"), form.cleaned_data.get("installation_position", ""))
    return module
