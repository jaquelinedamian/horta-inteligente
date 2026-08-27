from django.conf import settings
from django.db import models

from accounts.models import Organization
from core.models import BaseModel
from gardens.models import Garden, GardenModule


class MaintenancePlan(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="maintenance_plans")
    name = models.CharField(max_length=120)
    interval_days = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    checklist = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.name


class MaintenanceTask(BaseModel):
    plan = models.ForeignKey(MaintenancePlan, on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    is_required = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("plan", "position")

    def __str__(self):
        return f"{self.plan.name} — {self.name}"


class WorkOrder(BaseModel):
    class Kind(models.TextChoices):
        PREVENTIVE = "preventive", "Preventiva"
        CORRECTIVE = "corrective", "Corretiva"
        INSTALLATION = "installation", "Instalação"
    class Status(models.TextChoices):
        OPEN = "open", "Aberta"
        SCHEDULED = "scheduled", "Agendada"
        IN_PROGRESS = "in_progress", "Em andamento"
        COMPLETED = "completed", "Concluída"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="work_orders")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="work_orders")
    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="work_orders")
    maintenance_plan = models.ForeignKey(MaintenancePlan, on_delete=models.SET_NULL, null=True, blank=True, related_name="work_orders")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    priority = models.PositiveSmallIntegerField(default=3)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status", "scheduled_for"])]

    def __str__(self):
        return self.title


class Assignment(BaseModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="work_assignments")
    assigned_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["work_order", "user"], name="uniq_work_order_assignee")]


class WorkTask(BaseModel):
    work_order = models.ForeignKey(WorkOrder, on_delete=models.CASCADE, related_name="tasks")
    description = models.CharField(max_length=255)
    position = models.PositiveSmallIntegerField(default=0)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)


class MaintenanceRecord(BaseModel):
    work_order = models.OneToOneField(WorkOrder, on_delete=models.PROTECT, related_name="record")
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="maintenance_records")
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    parts_used = models.JSONField(default=list, blank=True)
    cost_cents = models.PositiveIntegerField(default=0)


class Incident(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="incidents")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="incidents")
    module = models.ForeignKey(GardenModule, on_delete=models.PROTECT, null=True, blank=True, related_name="incidents")
    device = models.ForeignKey("devices.Device", on_delete=models.PROTECT, null=True, blank=True, related_name="incidents")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="incidents")
    title = models.CharField(max_length=180)
    description = models.TextField()
    severity = models.PositiveSmallIntegerField(default=2)
    occurred_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)


class Visit(BaseModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Agendada"
        IN_PROGRESS = "in_progress", "Em andamento"
        COMPLETED = "completed", "Concluída"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="visits")
    garden = models.ForeignKey(Garden, on_delete=models.PROTECT, related_name="visits")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="visits")
    visit_type = models.CharField(max_length=80)
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    notes = models.TextField(blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(blank=True)
    conclusion = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["technician", "scheduled_start", "status"])]

    def __str__(self):
        return f"{self.organization.name} — {self.scheduled_start:%d/%m/%Y %H:%M}"


class ChecklistExecution(BaseModel):
    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="checklist_execution")
    items = models.JSONField(default=list)
    completed_at = models.DateTimeField(null=True, blank=True)


class SupportTicket(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Aberto"
        IN_PROGRESS = "in_progress", "Em atendimento"
        RESOLVED = "resolved", "Resolvido"

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="support_tickets")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="support_tickets")
    category = models.CharField(max_length=40)
    subject = models.CharField(max_length=180)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    garden = models.ForeignKey(Garden, on_delete=models.SET_NULL, null=True, blank=True, related_name="support_tickets")
    module = models.ForeignKey(GardenModule, on_delete=models.SET_NULL, null=True, blank=True, related_name="support_tickets")
    device = models.ForeignKey("devices.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="support_tickets")
    priority = models.PositiveSmallIntegerField(default=3)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_support_tickets")
    concluded_at = models.DateTimeField(null=True, blank=True)
    generated_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="support_tickets")

    def __str__(self):
        return self.subject


class Supplier(BaseModel):
    name = models.CharField(max_length=180)
    tax_id = models.CharField("CNPJ", max_length=30, blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address = models.TextField(blank=True)
    product_types = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "fornecedor"
        verbose_name_plural = "fornecedores"

    def __str__(self):
        return self.name


class InventoryCategory(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoria de estoque"
        verbose_name_plural = "categorias de estoque"

    def __str__(self):
        return self.name


class InventoryItem(BaseModel):
    class Category(models.TextChoices):
        MODULE = "module", "Módulo"
        SEEDLING = "seedling", "Muda"
        SUBSTRATE = "substrate", "Substrato"
        PUMP = "pump", "Bomba"
        SENSOR = "sensor", "Sensor"
        PART = "part", "Peça"

    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=60, unique=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    minimum_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=20, default="un")
    inventory_category = models.ForeignKey(InventoryCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="items")
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=120, blank=True)
    primary_supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="inventory_items")
    reserved_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    reorder_point = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    average_cost_cents = models.PositiveIntegerField(default=0)
    reference_price_cents = models.PositiveIntegerField(null=True, blank=True)
    tracks_lots = models.BooleanField(default=False)
    tracks_expiration = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    physical_location = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "item de estoque"
        verbose_name_plural = "itens de estoque"

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    def __str__(self):
        return f"{self.sku} — {self.name}"


class StockLot(BaseModel):
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="lots")
    code = models.CharField(max_length=80)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_lots")
    received_at = models.DateTimeField()
    manufactured_at = models.DateField(null=True, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    available_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit_cost_cents = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "lote de estoque"
        verbose_name_plural = "lotes de estoque"
        constraints = [models.UniqueConstraint(fields=["item", "code"], name="uniq_item_stock_lot")]

    def __str__(self):
        return f"{self.item.name} — lote {self.code}"


class StockMovement(BaseModel):
    class Kind(models.TextChoices):
        ENTRY = "entry", "Entrada"
        EXIT = "exit", "Saída"
        VISIT_USAGE = "visit_usage", "Consumo em visita"
        RESERVE = "reserve", "Reserva"
        RELEASE = "release", "Liberação de reserva"
        ADJUSTMENT = "adjustment", "Ajuste"
        LOSS = "loss", "Perda"
        EXPIRATION = "expiration", "Vencimento"
        TRANSFER = "transfer", "Transferência"

    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="movements")
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    visit = models.ForeignKey(Visit, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    work_order = models.ForeignKey(WorkOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    garden = models.ForeignKey(Garden, on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    cycle = models.ForeignKey("crops.PlantingCycle", on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_movements")
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "movimentação de estoque"
        verbose_name_plural = "movimentações de estoque"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.item.name} ({self.quantity} {self.unit})"


class VisitMaterialUsage(BaseModel):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="materials_used")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="visit_usages")
    lot = models.ForeignKey(StockLot, on_delete=models.PROTECT, null=True, blank=True, related_name="visit_usages")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=20)
    reason = models.CharField(max_length=180, blank=True)

    def __str__(self):
        return f"{self.item.name} — {self.quantity} {self.unit}"
