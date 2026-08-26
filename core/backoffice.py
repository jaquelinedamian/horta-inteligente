from dataclasses import dataclass

from accounts.models import Address, Membership, Organization, User
from crops.models import Crop, CropRequirement, Cultivar, PlantingCycle
from devices.models import Alert, AlertRule, Channel, Device, DeviceCommand, DeviceCredential, DeviceHeartbeat, DeviceModel, LightingSchedule, TelemetryReading
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from operations.models import Assignment, ChecklistExecution, InventoryItem, MaintenancePlan, MaintenanceRecord, SupportTicket, Visit, WorkOrder
from subscriptions.models import Payment, Plan, PlanFeature, PlanVersion, Subscription, SubscriptionEvent


@dataclass(frozen=True)
class Resource:
    title: str
    model: type
    fields: tuple[str, ...] = ()
    search: tuple[str, ...] = ()
    readonly: bool = False
    ordering: tuple[str, ...] = ("-updated_at",)


RESOURCES = {
    "organizations": Resource("Organizações", Organization, ("name", "slug", "kind", "tax_id", "is_active"), ("name", "slug", "tax_id")),
    "memberships": Resource("Membros", Membership, ("organization", "user", "role", "is_active"), ("organization__name", "user__email", "user__full_name")),
    "addresses": Resource("Endereços", Address, ("organization", "label", "street", "number", "complement", "district", "city", "state", "postal_code"), ("organization__name", "street", "city", "postal_code")),
    "employees": Resource("Funcionários", User, ("full_name", "email", "phone", "is_staff", "is_active"), ("full_name", "email"), ordering=("full_name",)),
    "plans": Resource("Planos", Plan, ("name", "code", "description", "is_active"), ("name", "code")),
    "plan-versions": Resource("Versões de plano", PlanVersion, ("plan", "version", "price_cents", "currency", "billing_interval_months", "effective_from", "retired_at"), ("plan__name",)),
    "plan-features": Resource("Recursos e limites", PlanFeature, ("plan_version", "key", "enabled", "limit"), ("plan_version__plan__name", "key")),
    "subscriptions": Resource("Assinaturas", Subscription, ("organization", "plan_version", "status", "current_period_start", "current_period_end", "canceled_at", "provider", "provider_reference"), ("organization__name", "plan_version__plan__name", "provider_reference")),
    "subscription-events": Resource("Histórico de assinaturas", SubscriptionEvent, search=("subscription__organization__name", "event_type", "idempotency_key"), readonly=True),
    "payments": Resource("Pagamentos", Payment, ("subscription", "amount_cents", "currency", "status", "due_at", "paid_at", "provider_reference"), ("subscription__organization__name", "provider_reference")),
    "crops": Resource("Culturas", Crop, ("common_name", "scientific_name", "code", "description", "difficulty", "light_requirement", "uses", "is_available"), ("common_name", "scientific_name", "code")),
    "cultivars": Resource("Cultivares", Cultivar, ("crop", "name", "days_to_harvest"), ("crop__common_name", "name")),
    "crop-requirements": Resource("Requisitos de cultivo", CropRequirement, ("cultivar", "metric", "unit", "minimum", "maximum", "target"), ("cultivar__name", "metric")),
    "cycles": Resource("Ciclos de cultivo", PlantingCycle, ("module", "cultivar", "status", "planted_at", "expected_harvest_at", "finished_at", "notes"), ("module__name", "module__serial_number", "cultivar__name")),
    "gardens": Resource("Hortas", Garden, ("organization", "name", "code", "address", "timezone", "is_active"), ("name", "code", "organization__name")),
    "module-types": Resource("Tipos de módulo", ModuleType, ("name", "code", "capabilities", "description"), ("name", "code")),
    "modules": Resource("Módulos", GardenModule, ("organization", "module_type", "serial_number", "name", "status"), ("name", "serial_number", "organization__name")),
    "installations": Resource("Histórico de instalações", ModuleInstallation, ("module", "garden", "position_label", "installed_at", "removed_at"), ("module__name", "module__serial_number", "garden__name")),
    "device-models": Resource("Modelos de dispositivo", DeviceModel, ("manufacturer", "name", "code", "hardware_platform", "capabilities"), ("manufacturer", "name", "code")),
    "devices": Resource("Dispositivos", Device, ("organization", "model", "module", "serial_number", "name", "status", "firmware_version", "metadata"), ("name", "serial_number", "organization__name", "firmware_version")),
    "channels": Resource("Sensores e canais", Channel, ("device", "key", "name", "kind", "metric", "unit", "value_type", "pin", "configuration", "is_enabled"), ("device__name", "name", "metric", "key")),
    "credentials": Resource("Credenciais de dispositivos", DeviceCredential, search=("device__name", "name", "key_prefix"), readonly=True),
    "heartbeats": Resource("Heartbeats", DeviceHeartbeat, search=("device__name", "firmware_version"), readonly=True),
    "telemetry": Resource("Telemetria", TelemetryReading, search=("channel__device__organization__name", "channel__device__name", "channel__name", "channel__metric"), readonly=True, ordering=("-recorded_at",)),
    "commands": Resource("Comandos", DeviceCommand, ("device", "channel", "command_type", "payload", "status", "idempotency_key", "not_before", "expires_at"), ("device__name", "channel__name", "command_type", "idempotency_key")),
    "alert-rules": Resource("Regras de alerta", AlertRule, ("organization", "channel", "name", "operator", "threshold", "severity", "cooldown_seconds", "is_active"), ("organization__name", "channel__name", "name")),
    "alerts": Resource("Alertas", Alert, ("rule", "reading", "status", "message", "opened_at", "acknowledged_at", "resolved_at"), ("rule__name", "rule__organization__name", "message")),
    "lighting": Resource("Programação de iluminação", LightingSchedule, ("actuator", "name", "timezone", "days_of_week", "start_time", "end_time", "enabled"), ("actuator__device__name", "name")),
    "orders": Resource("Ordens de serviço", WorkOrder, ("organization", "garden", "module", "device", "maintenance_plan", "kind", "status", "title", "description", "priority", "scheduled_for", "completed_at"), ("title", "organization__name", "garden__name")),
    "assignments": Resource("Atribuições", Assignment, ("work_order", "user", "assigned_at"), ("work_order__title", "user__full_name", "user__email")),
    "visits": Resource("Visitas e agenda", Visit, ("organization", "garden", "work_order", "technician", "visit_type", "scheduled_start", "scheduled_end", "status", "notes"), ("organization__name", "garden__name", "technician__full_name", "visit_type")),
    "checklists": Resource("Checklists executados", ChecklistExecution, search=("visit__organization__name",), readonly=True),
    "maintenance": Resource("Planos de manutenção", MaintenancePlan, ("organization", "name", "interval_days", "is_active", "checklist"), ("organization__name", "name")),
    "maintenance-records": Resource("Registros de manutenção", MaintenanceRecord, ("work_order", "performed_by", "started_at", "finished_at", "notes", "parts_used", "cost_cents"), ("work_order__title", "performed_by__full_name")),
    "tickets": Resource("Chamados de suporte", SupportTicket, ("organization", "opened_by", "category", "subject", "description", "status"), ("organization__name", "opened_by__email", "subject")),
    "inventory": Resource("Estoque", InventoryItem, ("name", "sku", "category", "quantity", "minimum_quantity", "unit"), ("name", "sku", "category")),
}

ALIASES = {"clients": "organizations", "agenda": "visits", "finance": "payments"}


def get_resource(section):
    return RESOURCES.get(ALIASES.get(section, section))
