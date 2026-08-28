from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import GardenModule, ModuleInstallation


@transaction.atomic
def install_module(module, garden, installed_at=None, position_label=""):
    if module.organization_id != garden.organization_id:
        raise ValidationError("O módulo e a horta precisam pertencer ao mesmo cliente.")
    installed_at = installed_at or timezone.now()
    active = ModuleInstallation.objects.select_for_update().filter(module=module, removed_at__isnull=True).select_related("garden").first()
    if active:
        raise ValidationError(f"Este módulo já está instalado na horta {active.garden.name}. Use a ação de mover módulo.")
    installation = ModuleInstallation.objects.create(module=module, garden=garden, installed_at=installed_at, position_label=position_label)
    module.status = GardenModule.Status.INSTALLED
    module.installed_at = installed_at
    module.position_label = position_label
    module.last_changed_at = installed_at
    module.save(update_fields=["status", "installed_at", "position_label", "last_changed_at", "updated_at"])
    return installation


@transaction.atomic
def move_module(module, garden, moved_at=None, position_label=""):
    if module.organization_id != garden.organization_id:
        raise ValidationError("O módulo e a horta precisam pertencer ao mesmo cliente.")
    moved_at = moved_at or timezone.now()
    active = ModuleInstallation.objects.select_for_update().filter(module=module, removed_at__isnull=True).first()
    if not active:
        raise ValidationError("Este módulo não possui uma instalação ativa para mover.")
    active.removed_at = moved_at
    active.save(update_fields=["removed_at", "updated_at"])
    installation = ModuleInstallation.objects.create(module=module, garden=garden, installed_at=moved_at, position_label=position_label)
    module.status = GardenModule.Status.INSTALLED
    module.installed_at = moved_at
    module.position_label = position_label
    module.last_changed_at = moved_at
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


def create_physical_module(form):
    organization = getattr(form, "organization", None) or form.cleaned_data.get("organization")
    if not organization:
        raise ValidationError("Informe o cliente responsável pelo módulo.")
    if hasattr(form, "cleaned_data") and "placement" in form.cleaned_data:
        return create_customer_module(form, organization)
    module = form.save(commit=False)
    module.status = GardenModule.Status.STOCK
    module.save()
    return module
