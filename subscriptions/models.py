from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import Organization
from core.models import BaseModel


class Plan(BaseModel):
    name = models.CharField(max_length=100)
    code = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    commercial_title = models.CharField(max_length=160, blank=True)
    subtitle = models.CharField(max_length=220, blank=True)
    short_copy = models.CharField(max_length=300, blank=True)
    ideal_for = models.TextField(blank=True)
    installation_fee_cents = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)
    image_url = models.URLField(blank=True)
    exclusions = models.TextField(blank=True)
    faq = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PlanVersion(BaseModel):
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    price_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    billing_interval_months = models.PositiveSmallIntegerField(default=1)
    effective_from = models.DateTimeField()
    retired_at = models.DateTimeField(null=True, blank=True)
    installation_fee_cents = models.PositiveIntegerField(default=0)
    commercial_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan", "version"], name="uniq_plan_version")]

    def __str__(self):
        return f"{self.plan.name} — R$ {self.price_cents / 100:.2f}/{self.billing_interval_months} mês(es)"


class PlanFeature(BaseModel):
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.CASCADE, related_name="features")
    key = models.SlugField(max_length=80)
    enabled = models.BooleanField(default=True)
    limit = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["plan_version", "key"], name="uniq_plan_feature")]


class PlanEntitlement(BaseModel):
    class Period(models.TextChoices):
        ONCE = "once", "Único"
        MONTH = "month", "Mensal"
        QUARTER = "quarter", "Trimestral"
        SEMESTER = "semester", "Semestral"
        YEAR = "year", "Anual"

    plan_version = models.ForeignKey(PlanVersion, on_delete=models.CASCADE, related_name="entitlements")
    benefit_type = models.SlugField(max_length=80)
    name = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    period = models.CharField(max_length=20, choices=Period.choices, default=Period.MONTH)
    unlimited = models.BooleanField(default=False)
    carries_balance = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"{self.name} — {self.plan_version.plan.name}"


class Coupon(BaseModel):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", "Percentual"
        FIXED = "fixed", "Valor fixo"

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    maximum_discount_cents = models.PositiveIntegerField(null=True, blank=True)
    minimum_purchase_cents = models.PositiveIntegerField(default=0)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    maximum_uses = models.PositiveIntegerField(null=True, blank=True)
    limit_per_customer = models.PositiveIntegerField(default=1)
    new_customers_only = models.BooleanField(default=False)
    first_charge_only = models.BooleanField(default=False)
    applicable_charges = models.PositiveSmallIntegerField(default=1)
    applies_to_all_plans = models.BooleanField(default=True)
    plans = models.ManyToManyField(Plan, blank=True, related_name="coupons")
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="exclusive_coupons")

    def __str__(self):
        return f"{self.code} — {self.name}"

    def calculate_discount(self, gross_cents):
        if gross_cents < self.minimum_purchase_cents:
            return 0
        discount = round(gross_cents * float(self.value) / 100) if self.discount_type == self.DiscountType.PERCENT else round(float(self.value) * 100)
        if self.maximum_discount_cents is not None:
            discount = min(discount, self.maximum_discount_cents)
        return min(gross_cents, max(0, discount))


class Subscription(BaseModel):
    class Status(models.TextChoices):
        TRIALING = "trialing", "Em teste"
        ACTIVE = "active", "Ativa"
        PAST_DUE = "past_due", "Pagamento atrasado"
        SUSPENDED = "suspended", "Suspensa"
        CANCELED = "canceled", "Cancelada"

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="subscriptions")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIALING)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    canceled_at = models.DateTimeField(null=True, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    contracted_price_cents = models.PositiveIntegerField(null=True, blank=True)
    billing_day = models.PositiveSmallIntegerField(default=1)
    next_billing_at = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions")
    discount_cents = models.PositiveIntegerField(default=0)
    cancellation_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"])]


class SubscriptionEvent(BaseModel):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField()
    idempotency_key = models.CharField(max_length=120, unique=True, null=True, blank=True)


class Payment(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PAID = "paid", "Pago"
        FAILED = "failed", "Falhou"
        REFUNDED = "refunded", "Estornado"
        OVERDUE = "overdue", "Vencido"
        CANCELED = "canceled", "Cancelado"

    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="payments")
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="BRL")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    due_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True)
    competence = models.DateField(null=True, blank=True)
    gross_amount_cents = models.PositiveIntegerField(null=True, blank=True)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    discount_cents = models.PositiveIntegerField(default=0)
    payment_method = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.gross_amount_cents is None:
            self.gross_amount_cents = self.amount_cents
        if self.coupon_id:
            self.discount_cents = self.coupon.calculate_discount(self.gross_amount_cents)
            self.amount_cents = self.gross_amount_cents - self.discount_cents
        super().save(*args, **kwargs)


class CouponRedemption(BaseModel):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="coupon_redemptions")
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="coupon_redemptions")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, blank=True, related_name="coupon_redemptions")
    original_amount_cents = models.PositiveIntegerField()
    discount_cents = models.PositiveIntegerField()
    final_amount_cents = models.PositiveIntegerField()
    used_at = models.DateTimeField(default=timezone.now)

    def clean(self):
        if self.subscription.organization_id != self.organization_id:
            raise ValidationError("A assinatura pertence a outra organização.")


class CheckoutRequest(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        CONFIRMED = "confirmed", "Confirmado"
        CANCELED = "canceled", "Cancelado"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="checkout_requests")
    plan_version = models.ForeignKey(PlanVersion, on_delete=models.PROTECT, related_name="checkout_requests")
    selected_cultures = models.ManyToManyField("crops.Cultivar", blank=True, related_name="checkout_requests")
    selected_crops = models.ManyToManyField("crops.Crop", blank=True, related_name="checkout_crop_requests")
    installation_data = models.JSONField(default=dict, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
