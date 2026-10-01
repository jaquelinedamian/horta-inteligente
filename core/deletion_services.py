from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from accounts.models import Organization, User
from crops.models import Crop, Harvest, HarvestEvent, PlantingCycle
from devices.models import (
    Alert, AlertRule, Device, DeviceCommand, DeviceCredential, DeviceHeartbeat,
    GardenPhoto, LightingSchedule, SensorCalibration, TelemetryReading,
)
from gardens.models import Garden, GardenModule, ModuleInstallation
from operations.models import (
    Incident, InventoryItem, MaintenanceRecord, StockMovement, SupportTicket,
    Visit, WorkOrder,
)
from subscriptions.models import CheckoutRequest, CouponRedemption, Payment, Subscription


class DeletionBlocked(ValidationError):
    pass


@dataclass(frozen=True)
class DeletePolicy:
    label: str
    high_impact: bool = False
    deactivate_field: str | None = None


DELETE_POLICIES = {
    "gardens": DeletePolicy("Horta", True),
    "crops": DeletePolicy("Cultura", deactivate_field="is_available"),
    "employees": DeletePolicy("Funcionário", deactivate_field="is_active"),
    "visits": DeletePolicy("Visita"),
    "inventory": DeletePolicy("Item de estoque", deactivate_field="is_active"),
    "garden-models": DeletePolicy("Modelo de horta", deactivate_field="is_active"),
    "plans": DeletePolicy("Plano", deactivate_field="is_active"),
    "subscriptions": DeletePolicy("Assinatura", True),
    "devices": DeletePolicy("Dispositivo", True),
    "tickets": DeletePolicy("Chamado de suporte"),
}


def customer_deletion_summary(user):
    organizations = Organization.objects.filter(memberships__user=user).distinct()
    gardens = Garden.objects.filter(organization__in=organizations)
    devices = Device.objects.filter(organization__in=organizations)
    cycles = PlantingCycle.objects.filter(organization__in=organizations)
    return {
        "Hortas": gardens.count(),
        "Assinaturas": Subscription.objects.filter(organization__in=organizations).count(),
        "Dispositivos": devices.count(),
        "Cultivos": cycles.count(),
        "Visitas": Visit.objects.filter(organization__in=organizations).count(),
        "Chamados": SupportTicket.objects.filter(organization__in=organizations).count(),
        "Fotografias": GardenPhoto.objects.filter(garden__in=gardens).count(),
    }


def garden_deletion_summary(garden):
    device_ids = Device.objects.filter(garden=garden).values("pk")
    return {
        "Cultivos": garden.planting_cycles.count(),
        "Dispositivos": device_ids.count(),
        "Fotografias": garden.photos.count(),
        "Visitas": garden.visits.count(),
        "Ordens de serviço": garden.work_orders.count(),
        "Chamados": garden.support_tickets.count(),
    }


def device_deletion_summary(device):
    channel_ids = device.channels.values("pk")
    return {
        "Credenciais": device.credentials.count(),
        "Telemetrias": TelemetryReading.objects.filter(channel__in=channel_ids).count(),
        "Fotografias": device.photos.count(),
        "Comandos": device.commands.count(),
    }


def object_deletion_summary(section, obj):
    if section == "gardens":
        return garden_deletion_summary(obj)
    if section == "devices":
        return device_deletion_summary(obj)
    if section == "crops":
        return {"Cultivos registrados": obj.planting_cycles.count(), "Variedades": obj.cultivars.count()}
    if section == "employees":
        return {"Visitas": obj.visits.count(), "Ordens atribuídas": obj.work_assignments.count(), "Movimentações": obj.stock_movements.count()}
    if section == "inventory":
        return {"Movimentações": obj.movements.count(), "Lotes": obj.lots.count(), "Usos em visitas": obj.visit_usages.count()}
    if section == "subscriptions":
        return {"Hortas": obj.gardens.count(), "Pagamentos": obj.payments.count(), "Eventos": obj.events.count()}
    if section == "garden-models":
        return {"Hortas": obj.gardens.count(), "Planos": obj.plans.count()}
    if section == "plans":
        return {"Versões": obj.versions.count(), "Assinaturas": Subscription.objects.filter(plan_version__plan=obj).count()}
    return {}


def requires_strong_confirmation(section, summary):
    policy = DELETE_POLICIES[section]
    return policy.high_impact or any(summary.values())


def can_deactivate(section, summary):
    return DELETE_POLICIES[section].deactivate_field and any(summary.values())


def deactivate_object(section, obj):
    field = DELETE_POLICIES[section].deactivate_field
    if not field:
        raise DeletionBlocked("Este cadastro não possui opção de desativação.")
    setattr(obj, field, False)
    update_fields = [field]
    if any(model_field.name == "updated_at" for model_field in obj._meta.fields):
        update_fields.append("updated_at")
    obj.save(update_fields=update_fields)


def _delete_cycle(cycle):
    StockMovement.objects.filter(cycle=cycle).update(cycle=None)
    HarvestEvent.objects.filter(cycle=cycle).delete()
    Harvest.objects.filter(cycle=cycle).delete()
    cycle.delete()


@transaction.atomic
def delete_device_completely(device):
    if device.work_orders.exists() or device.incidents.exists():
        raise DeletionBlocked("O dispositivo possui histórico operacional. Exclua-o junto com a horta/cliente ou preserve o histórico.")
    DeviceCredential.objects.filter(device=device, is_active=True).update(is_active=False)
    channel_ids = list(device.channels.values_list("pk", flat=True))
    Alert.objects.filter(rule__channel_id__in=channel_ids).delete()
    AlertRule.objects.filter(channel_id__in=channel_ids).delete()
    DeviceCommand.objects.filter(device=device).delete()
    LightingSchedule.objects.filter(actuator_id__in=channel_ids).delete()
    SensorCalibration.objects.filter(channel_id__in=channel_ids).delete()
    TelemetryReading.objects.filter(channel_id__in=channel_ids).delete()
    GardenPhoto.objects.filter(device=device).delete()
    DeviceHeartbeat.objects.filter(device=device).delete()
    DeviceCredential.objects.filter(device=device).delete()
    device.channels.all().delete()
    device.delete()


def _delete_work_order(order):
    Visit.objects.filter(work_order=order).update(work_order=None)
    SupportTicket.objects.filter(generated_order=order).update(generated_order=None)
    StockMovement.objects.filter(work_order=order).update(work_order=None)
    order.incidents.update(work_order=None)
    MaintenanceRecord.objects.filter(work_order=order).delete()
    order.delete()


@transaction.atomic
def delete_garden_completely(garden):
    StockMovement.objects.filter(garden=garden).update(garden=None)
    SupportTicket.objects.filter(garden=garden).update(garden=None)
    for visit in list(Visit.objects.filter(garden=garden)):
        visit.delete()
    Incident.objects.filter(garden=garden).delete()
    for order in list(WorkOrder.objects.filter(garden=garden)):
        _delete_work_order(order)
    for cycle in list(PlantingCycle.objects.filter(garden=garden)):
        _delete_cycle(cycle)
    module_ids = list(ModuleInstallation.objects.filter(garden=garden, removed_at__isnull=True).values_list("module_id", flat=True))
    ModuleInstallation.objects.filter(garden=garden).delete()
    devices = Device.objects.filter(garden=garden) | Device.objects.filter(module_id__in=module_ids)
    for device in list(devices.distinct()):
        SupportTicket.objects.filter(device=device).update(device=None)
        delete_device_completely(device)
    GardenPhoto.objects.filter(garden=garden).delete()
    garden.delete()


def _delete_subscription(subscription):
    subscription.gardens.update(subscription=None)
    CouponRedemption.objects.filter(subscription=subscription).delete()
    Payment.objects.filter(subscription=subscription).delete()
    subscription.delete()


@transaction.atomic
def delete_customer_completely(user):
    organizations = list(Organization.objects.filter(memberships__user=user).distinct())
    for organization in organizations:
        for garden in list(organization.gardens.all()):
            delete_garden_completely(garden)
        for module in list(organization.garden_modules.all()):
            for cycle in list(module.planting_cycles.all()):
                _delete_cycle(cycle)
            ModuleInstallation.objects.filter(module=module).delete()
            for device in list(module.devices.all()):
                delete_device_completely(device)
            module.delete()
        for order in list(organization.work_orders.all()):
            _delete_work_order(order)
        organization.visits.all().delete()
        organization.incidents.all().delete()
        organization.support_tickets.all().delete()
        for device in list(organization.devices.all()):
            delete_device_completely(device)
        for subscription in list(organization.subscriptions.all()):
            _delete_subscription(subscription)
        CouponRedemption.objects.filter(organization=organization).delete()
        organization.delete()
    user.delete()


@transaction.atomic
def delete_administrative_object(section, obj):
    if section == "gardens":
        return delete_garden_completely(obj)
    if section == "devices":
        return delete_device_completely(obj)
    if section == "subscriptions":
        return _delete_subscription(obj)
    if section == "plans":
        versions = obj.versions.all()
        if Subscription.objects.filter(plan_version__in=versions).exists() or CheckoutRequest.objects.filter(plan_version__in=versions).exists():
            raise DeletionBlocked("O plano já foi utilizado. Desative-o para preservar assinaturas e checkouts.")
        for version in list(versions):
            version.delete()
        return obj.delete()
    summary = object_deletion_summary(section, obj)
    if section in {"crops", "employees", "inventory"} and any(summary.values()):
        raise DeletionBlocked("Este cadastro possui histórico. Use Desativar para preservar as referências existentes.")
    try:
        obj.delete()
    except ProtectedError as error:
        raise DeletionBlocked("O cadastro possui relações protegidas e não pode ser excluído. Desative-o quando essa opção estiver disponível.") from error
