from dataclasses import dataclass

from accounts.models import Address, Membership, Organization, User
from crops.models import (Crop, CropCultivationProfile, CropNutritionPlan, CropRequirement, CropStageProfile,
    Cultivar, Fertilizer, HarvestEvent, PlantingCycle, SubstrateMaterial, SubstrateRecipe, SubstrateRecipeComponent)
from devices.models import (Alert, AlertRule, Channel, Device, DeviceCommand, DeviceCredential, DeviceHeartbeat,
    DeviceModel, LightingSchedule, SensorCalibration, TelemetryMetric, TelemetryReading)
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from operations.models import (Assignment, ChecklistExecution, InventoryCategory, InventoryItem, MaintenancePlan,
    MaintenanceRecord, MaintenanceTask, StockLot, StockMovement, Supplier, SupportTicket, Visit,
    VisitMaterialUsage, WorkOrder)
from subscriptions.models import (Coupon, CouponRedemption, Payment, Plan, PlanEntitlement, PlanFeature,
    PlanVersion, Subscription, SubscriptionEvent)


@dataclass(frozen=True)
class Resource:
    title: str
    model: type
    fields: tuple[str, ...] = ()
    search: tuple[str, ...] = ()
    readonly: bool = False
    ordering: tuple[str, ...] = ("-updated_at",)


def r(title, model, fields, search=()):
    return Resource(title, model, tuple(fields.split()), tuple(search))


RESOURCES = {
    "organizations": r("Organizações", Organization, "name slug kind tax_id primary_contact phone email billing_email internal_notes is_active", ("name", "slug", "tax_id")),
    "memberships": r("Membros", Membership, "organization user role is_active", ("organization__name", "user__email")),
    "addresses": r("Endereços", Address, "organization label street number complement district city state postal_code country address_type access_instructions property_type floor has_elevator has_doorman condominium_restrictions access_notes latitude longitude", ("organization__name", "street", "city")),
    "employees": Resource("Funcionários", User, ("full_name", "email", "phone", "tax_id", "birth_date", "is_staff", "is_active"), ("full_name", "email"), ordering=("full_name",)),
    "plans": r("Planos", Plan, "name code commercial_title subtitle short_copy description ideal_for installation_fee_cents is_public is_featured display_order image_url exclusions is_active", ("name", "code")),
    "plan-versions": r("Versões de plano", PlanVersion, "plan version price_cents currency billing_interval_months effective_from retired_at installation_fee_cents", ("plan__name",)),
    "plan-features": r("Recursos legados", PlanFeature, "plan_version key enabled limit", ("key",)),
    "entitlements": r("Itens incluídos no plano", PlanEntitlement, "plan_version benefit_type name description quantity unit period unlimited carries_balance is_featured display_order", ("name", "plan_version__plan__name")),
    "coupons": r("Cupons", Coupon, "code name description is_active discount_type value maximum_discount_cents minimum_purchase_cents valid_from valid_until maximum_uses limit_per_customer new_customers_only first_charge_only applicable_charges applies_to_all_plans plans organization", ("code", "name")),
    "coupon-redemptions": Resource("Usos de cupons", CouponRedemption, search=("coupon__code", "organization__name"), readonly=True),
    "subscriptions": r("Assinaturas", Subscription, "organization plan_version status current_period_start current_period_end contracted_price_cents billing_day next_billing_at auto_renew coupon discount_cents canceled_at cancellation_reason notes provider provider_reference", ("organization__name", "plan_version__plan__name")),
    "subscription-events": Resource("Histórico de assinaturas", SubscriptionEvent, search=("subscription__organization__name", "event_type"), readonly=True),
    "payments": r("Pagamentos", Payment, "subscription competence gross_amount_cents coupon discount_cents amount_cents currency due_at paid_at payment_method status provider_reference notes", ("subscription__organization__name", "provider_reference")),
    "crops": r("Culturas", Crop, "common_name scientific_name code description difficulty light_requirement uses is_available botanical_family category origin life_cycle edible_part page_title short_description flavor aroma is_featured image_url minimum_temperature ideal_temperature_min ideal_temperature_max maximum_temperature minimum_humidity maximum_humidity light_hours target_ppfd root_depth_cm minimum_pot_liters allows_regrowth estimated_harvests cut_interval_days", ("common_name", "scientific_name", "code")),
    "cultivars": r("Variedades", Cultivar, "crop name code description size color flavor vigor resistance days_to_harvest specific_characteristics is_active", ("crop__common_name", "name")),
    "crop-requirements": r("Requisitos de cultivo", CropRequirement, "cultivar metric unit minimum maximum target", ("cultivar__name", "metric")),
    "cultivation-profiles": r("Perfis de cultivo", CropCultivationProfile, "crop cultivar cultivation_system name description is_active target_temperature_min target_temperature_max target_humidity_min target_humidity_max photoperiod_hours target_ppfd substrate_moisture_min substrate_moisture_max initial_irrigation_amount irrigation_unit initial_irrigation_interval_hours ph_min ph_target ph_max ec_min ec_target ec_max", ("crop__common_name", "name")),
    "crop-stages": r("Estágios", CropStageProfile, "profile name position estimated_duration_days temperature humidity photoperiod_hours ppfd substrate_moisture irrigation_notes ph ec fertilization_notes notes", ("name",)),
    "cycles": r("Ciclos de cultivo", PlantingCycle, "organization garden module crop cultivar cultivation_profile substrate_recipe nutrition_plan origin batch_code planted_at current_stage expected_harvest_at expected_end_at status responsible closure_reason maximum_cuts cuts_completed next_harvest_at notes", ("module__name", "cultivar__name")),
    "harvests": r("Colheitas", HarvestEvent, "cycle harvest_number harvested_at quantity unit quality notes", ("cycle__cultivar__name",)),
    "substrates": r("Substratos", SubstrateMaterial, "name category manufacturer supplier description organic_matter_percent ph ec density water_retention_percent aeration_percent porosity_percent particle_size stock_unit is_active", ("name",)),
    "substrate-recipes": r("Receitas de substrato", SubstrateRecipe, "name code version description intended_use target_ph target_ec is_active", ("name", "code")),
    "substrate-components": r("Componentes de receitas", SubstrateRecipeComponent, "recipe material percentage quantity unit", ("recipe__name", "material__name")),
    "fertilizers": r("Fertilizantes", Fertilizer, "name code manufacturer supplier kind form nitrogen phosphorus potassium micronutrients unit recommended_dilution application_method is_active", ("name", "code")),
    "nutrition-plans": r("Planos nutricionais", CropNutritionPlan, "crop cultivar cultivation_profile stage fertilizer dose unit dilution_volume frequency_days method target_ec target_ph notes", ("crop__common_name", "fertilizer__name")),
    "gardens": r("Hortas", Garden, "organization name code address timezone responsible subscription status location_name position_description sunlight socket_nearby wifi_available wifi_quality pets children restrictions site_notes equipment_model installed_at module_capacity reservoir_liters grow_light_type pump_model controller_model technical_status primary_technician last_visit_at next_visit_at operational_notes is_active", ("name", "code", "organization__name")),
    "module-types": r("Tipos de módulos", ModuleType, "name code capabilities description width_cm height_cm depth_cm pot_volume_liters substrate_capacity_liters water_capacity_liters supports_irrigation supports_lighting supports_sensors recommended_crops is_active", ("name", "code")),
    "modules": r("Módulos", GardenModule, "organization module_type serial_number name qr_identifier status position_label pot_volume_liters substrate_capacity_liters installed_at last_changed_at next_change_at notes", ("name", "serial_number")),
    "installations": r("Instalações", ModuleInstallation, "module garden position_label installed_at removed_at", ("module__serial_number", "garden__name")),
    "device-models": r("Modelos de dispositivos", DeviceModel, "manufacturer name code hardware_platform capabilities", ("name", "code")),
    "devices": r("Dispositivos", Device, "organization model module serial_number name status firmware_version metadata", ("name", "serial_number")),
    "metrics": r("Métricas monitoradas", TelemetryMetric, "code name description default_unit data_type minimum_expected maximum_expected is_active", ("code", "name")),
    "channels": r("Canais", Channel, "device key name kind metric metric_definition unit value_type pin configuration is_enabled", ("device__name", "name", "metric")),
    "credentials": Resource("Credenciais", DeviceCredential, search=("device__name", "key_prefix"), readonly=True),
    "heartbeats": Resource("Heartbeats", DeviceHeartbeat, search=("device__name",), readonly=True),
    "telemetry": Resource("Telemetria", TelemetryReading, search=("channel__device__name", "channel__name"), readonly=True, ordering=("-recorded_at",)),
    "calibrations": r("Calibrações", SensorCalibration, "channel calibrated_at reference_value measured_value offset scale_factor responsible next_calibration_at notes", ("channel__name",)),
    "commands": r("Comandos", DeviceCommand, "device channel command_type payload status idempotency_key not_before expires_at", ("device__name", "command_type")),
    "alert-rules": r("Regras de alerta", AlertRule, "organization channel name operator threshold severity cooldown_seconds is_active", ("name",)),
    "alerts": r("Alertas", Alert, "rule reading status message opened_at acknowledged_at resolved_at", ("message",)),
    "lighting": r("Iluminação", LightingSchedule, "actuator name timezone days_of_week start_time end_time enabled", ("name",)),
    "orders": r("Ordens de serviço", WorkOrder, "organization garden module device maintenance_plan kind status title description priority scheduled_for completed_at", ("title",)),
    "assignments": r("Atribuições", Assignment, "work_order user assigned_at", ("work_order__title",)),
    "visits": r("Visitas", Visit, "organization garden work_order technician visit_type scheduled_start scheduled_end actual_start actual_end status reason notes conclusion", ("organization__name",)),
    "checklists": Resource("Checklists executados", ChecklistExecution, readonly=True),
    "maintenance": r("Planos de manutenção", MaintenancePlan, "organization name interval_days is_active checklist", ("name",)),
    "maintenance-tasks": r("Tarefas de manutenção", MaintenanceTask, "plan name description is_required position", ("name",)),
    "maintenance-records": r("Registros de manutenção", MaintenanceRecord, "work_order performed_by started_at finished_at notes parts_used cost_cents", ("work_order__title",)),
    "tickets": r("Suporte", SupportTicket, "organization opened_by garden module device category priority subject description status assigned_to concluded_at generated_order", ("subject",)),
    "inventory": r("Itens de estoque", InventoryItem, "sku name inventory_category category description brand primary_supplier unit quantity reserved_quantity minimum_quantity reorder_point average_cost_cents reference_price_cents tracks_lots tracks_expiration is_active physical_location", ("name", "sku")),
    "inventory-categories": r("Categorias", InventoryCategory, "name description is_active", ("name",)),
    "stock-lots": r("Lotes", StockLot, "item code supplier received_at manufactured_at expires_at received_quantity available_quantity unit_cost_cents notes", ("item__name", "code")),
    "stock-movements": r("Movimentações", StockMovement, "item lot kind quantity unit occurred_at user supplier visit work_order garden cycle notes", ("item__name", "item__sku")),
    "visit-materials": r("Materiais em visitas", VisitMaterialUsage, "visit item lot quantity unit reason", ("item__name",)),
    "suppliers": r("Fornecedores", Supplier, "name tax_id contact_name phone email website address product_types is_active notes", ("name", "tax_id")),
}

ALIASES = {"clients": "organizations", "agenda": "visits", "finance": "payments"}


def get_resource(section):
    return RESOURCES.get(ALIASES.get(section, section))
