from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import models, transaction
from django.forms import modelform_factory
from django.core.exceptions import FieldDoesNotExist
from django.utils import timezone

from accounts.models import Address, Membership, Organization, User
from devices.models import Channel
from subscriptions.models import Plan, PlanEntitlement, PlanVersion, Subscription
from subscriptions.selectors import get_available_plan_versions
from crops.models import Crop, PlantingCycle
from crops.selectors import get_available_cultivars
from gardens.models import Garden, GardenModule, ModuleInstallation


LABELS = {
    "organization": "Organização", "plan_version": "Plano / versão", "module_type": "Tipo de módulo",
    "serial_number": "Número de série", "common_name": "Nome comum", "scientific_name": "Nome científico",
    "is_active": "Ativo", "is_available": "Disponível", "current_period_start": "Início do período",
    "current_period_end": "Fim do período", "scheduled_start": "Início agendado", "scheduled_end": "Fim agendado",
    "scheduled_for": "Data agendada", "opened_by": "Aberto por", "performed_by": "Executado por",
    "minimum_quantity": "Quantidade mínima", "price_cents": "Preço em centavos", "interval_days": "Periodicidade em dias",
    "sku": "SKU", "name": "Nome", "inventory_category": "Categoria de estoque",
    "category": "Categoria", "description": "Descrição", "primary_supplier": "Fornecedor principal",
    "supplier": "Fornecedor", "unit": "Unidade", "quantity": "Quantidade",
    "reserved_quantity": "Estoque reservado", "reorder_point": "Ponto de reposição",
    "average_cost_cents": "Custo médio em centavos", "reference_price_cents": "Preço de referência em centavos",
    "tracks_lots": "Controlar lotes?", "tracks_expiration": "Controlar validade?",
    "physical_location": "Localização física", "brand": "Marca", "is_required": "Obrigatória",
    "created_at": "Criado em", "updated_at": "Atualizado em", "code": "Código",
    "commercial_title": "Título comercial", "short_copy": "Resumo comercial", "ideal_for": "Público ideal",
    "installation_fee_cents": "Taxa de instalação em centavos", "display_order": "Ordem de exibição",
    "is_public": "Visível no site", "is_featured": "Destaque", "metric_definition": "Métrica monitorada",
    "default_unit": "Unidade padrão", "data_type": "Tipo de dado",
    "slug": "Identificador", "kind": "Tipo", "tax_id": "CPF/CNPJ", "primary_contact": "Responsável principal",
    "phone": "Telefone", "email": "E-mail", "billing_email": "E-mail financeiro", "internal_notes": "Observações internas",
    "full_name": "Nome completo", "birth_date": "Data de nascimento", "is_staff": "Acesso administrativo",
    "version": "Versão", "currency": "Moeda", "billing_interval_months": "Periodicidade em meses",
    "effective_from": "Vigência inicial", "retired_at": "Encerrado em", "benefit_type": "Tipo de benefício",
    "period": "Período", "unlimited": "Ilimitado", "carries_balance": "Acumula saldo",
    "discount_type": "Tipo de desconto", "value": "Valor", "valid_from": "Início da validade", "valid_until": "Fim da validade",
    "maximum_uses": "Quantidade máxima de usos", "limit_per_customer": "Limite por cliente", "notes": "Observações",
    "status": "Status", "current_period_start": "Início", "current_period_end": "Fim", "contracted_price_cents": "Preço contratado em centavos",
    "billing_day": "Dia de vencimento", "next_billing_at": "Próxima cobrança", "auto_renew": "Renovação automática",
    "competence": "Competência", "gross_amount_cents": "Valor bruto em centavos", "discount_cents": "Desconto em centavos",
    "amount_cents": "Valor final em centavos", "due_at": "Vencimento", "paid_at": "Data do pagamento",
    "payment_method": "Forma de pagamento", "provider_reference": "Identificador externo",
    "scientific_name": "Nome científico", "difficulty": "Dificuldade", "light_requirement": "Necessidade de luz",
    "uses": "Usos", "botanical_family": "Família botânica", "origin": "Origem", "is_available": "Disponível",
    "manufacturer": "Fabricante", "stock_unit": "Unidade de estoque", "intended_use": "Uso indicado",
    "organization": "Organização", "address": "Endereço", "responsible": "Responsável", "module": "Módulo",
    "device": "Dispositivo", "channel": "Canal", "position": "Ordem", "enabled": "Ativo",
    "occurred_at": "Data", "received_at": "Data de entrada", "expires_at": "Validade", "manufactured_at": "Fabricação",
    "received_quantity": "Quantidade recebida", "available_quantity": "Quantidade disponível", "unit_cost_cents": "Custo unitário em centavos",
}


class OperationalModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.label = LABELS.get(name, field.label)
            try:
                model_field = self._meta.model._meta.get_field(name)
            except FieldDoesNotExist:
                model_field = None
            if model_field and model_field.has_default():
                field.required = False
            if isinstance(field, forms.ModelChoiceField):
                field.empty_label = "Selecione uma opção"
        if "plan_version" in self.fields:
            available = get_available_plan_versions()
            selected_id = self.data.get(self.add_prefix("plan_version")) if self.is_bound else getattr(self.instance, "plan_version_id", None)
            if selected_id:
                available = (available | PlanVersion.objects.filter(pk=selected_id)).distinct()
            self.fields["plan_version"].queryset = available
        if "cultivar" in self.fields:
            self.fields["cultivar"].queryset = get_available_cultivars()
            field.widget.attrs.setdefault("class", "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control")
            if isinstance(field.widget, forms.DateTimeInput):
                field.widget.input_type = "datetime-local"
                field.widget.format = "%Y-%m-%dT%H:%M"

    def clean(self):
        cleaned = super().clean()
        organization = cleaned.get("organization")
        for name in ("garden", "module", "device", "address", "subscription", "work_order"):
            related = cleaned.get(name)
            if organization and related and related.organization_id != organization.id:
                self.add_error(name, "Selecione um registro pertencente à organização escolhida.")
        subscription = cleaned.get("subscription")
        expected_organization_id = getattr(self, "customer_organization_id", None)
        if not organization and subscription and expected_organization_id and subscription.organization_id != expected_organization_id:
            self.add_error("subscription", "A assinatura pertence a outro cliente.")
        if self._meta.model is GardenModule and cleaned.get("status") == GardenModule.Status.INSTALLED:
            has_installation = bool(self.instance.pk and self.instance.installations.filter(removed_at__isnull=True).exists())
            if not has_installation:
                self.add_error("status", "Um módulo instalado precisa estar vinculado a uma horta. Use o fluxo de instalação do cliente.")
        if self._meta.model is ModuleInstallation:
            module, garden = cleaned.get("module"), cleaned.get("garden")
            if module and garden and module.organization_id != garden.organization_id:
                self.add_error("garden", "A horta pertence a outro cliente.")
        channel = cleaned.get("channel")
        if organization and channel and channel.device.organization_id != organization.id:
            self.add_error("channel", "O canal pertence a outra organização.")
        actuator = cleaned.get("actuator")
        if actuator and actuator.kind != Channel.Kind.ACTUATOR:
            self.add_error("actuator", "Selecione um canal do tipo atuador.")
        return cleaned


class CustomerModuleForm(OperationalModelForm):
    placement = forms.ChoiceField(label="Onde este módulo ficará agora?", choices=(("stock", "Em estoque / ainda não instalado"), ("install", "Instalar em uma horta deste cliente")), widget=forms.RadioSelect)
    garden = forms.ModelChoiceField(label="Horta", queryset=Garden.objects.none(), required=False)
    installation_position = forms.CharField(label="Posição na horta", max_length=100, required=False)
    installation_date = forms.DateTimeField(label="Data da instalação", required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    class Meta:
        model = GardenModule
        fields = ("module_type", "serial_number", "name", "qr_identifier", "position_label", "pot_volume_liters", "substrate_capacity_liters", "notes")

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        self.fields["garden"].queryset = Garden.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["installation_date"].initial = timezone.now()

    def clean(self):
        cleaned = super().clean()
        garden = cleaned.get("garden")
        if cleaned.get("placement") == "install" and not garden:
            self.add_error("garden", "Um módulo instalado precisa estar vinculado a uma horta.")
        if garden and garden.organization_id != self.organization.id:
            self.add_error("garden", "Selecione uma horta deste cliente.")
        return cleaned


class CustomerModuleInstallationForm(forms.Form):
    garden = forms.ModelChoiceField(label="Instalar na horta", queryset=Garden.objects.none())
    position_label = forms.CharField(label="Posição na horta", max_length=100, required=False)
    installed_at = forms.DateTimeField(label="Data da instalação", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["garden"].queryset = Garden.objects.filter(organization=organization, is_active=True).order_by("name")
        self.fields["installed_at"].initial = timezone.now()


class AvailabilityChoiceField(forms.TypedChoiceField):
    """Boolean radio that also accepts the legacy checkbox value during rollout."""

    def valid_value(self, value):
        return value == "on" or super().valid_value(value)


def resource_form_class(resource):
    if resource.model is User:
        return EmployeeForm
    if resource.model is Plan:
        return CommercialPlanForm
    if resource.model is Crop:
        return CropForm
    return modelform_factory(resource.model, form=OperationalModelForm, fields=resource.fields)


class CropForm(OperationalModelForm):
    is_available = AvailabilityChoiceField(
        label="Disponibilizar esta cultura?",
        choices=((True, "Ativa e disponível"), (False, "Manter inativa")),
        coerce=lambda value: value in (True, "True", "true", "1", "on"),
        widget=forms.RadioSelect,
        help_text="Quando ativa, esta cultura poderá aparecer no catálogo e ser escolhida pelos clientes.",
    )

    class Meta:
        model = Crop
        fields = ("common_name", "scientific_name", "code", "description", "difficulty", "light_requirement", "uses", "is_available", "botanical_family", "category", "origin", "life_cycle", "edible_part", "page_title", "short_description", "flavor", "aroma", "is_featured", "image_url", "minimum_temperature", "ideal_temperature_min", "ideal_temperature_max", "maximum_temperature", "minimum_humidity", "maximum_humidity", "light_hours", "target_ppfd", "root_depth_cm", "minimum_pot_liters", "allows_regrowth", "estimated_harvests", "cut_interval_days")

    def clean_is_available(self):
        available = self.cleaned_data["is_available"]
        if self.instance.pk and not available and self.instance.is_available:
            self.active_cycle_count = PlantingCycle.objects.filter(crop=self.instance, status=PlantingCycle.Status.ACTIVE).count()
        return available


class CommercialPlanForm(OperationalModelForm):
    monthly_price = forms.DecimalField(label="Preço mensal", max_digits=10, decimal_places=2, min_value=0.01, required=False, help_text="Obrigatório para publicar o plano no site e disponibilizá-lo para novas assinaturas.")
    effective_from = forms.DateTimeField(label="Início da vigência", required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}), help_text="Se vazio, a nova versão entra em vigor imediatamente.")
    included_items = forms.CharField(label="Itens incluídos", required=False, widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Um benefício por linha. Ex.: 3 módulos"}), help_text="Cria os benefícios da versão atual do plano.")

    class Meta:
        model = Plan
        fields = ("name", "code", "commercial_title", "subtitle", "short_copy", "description", "ideal_for", "installation_fee_cents", "is_public", "is_featured", "display_order", "image_url", "exclusions", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.versions.filter(retired_at__isnull=True).order_by("-version").first() if self.instance.pk else None
        if current and not self.is_bound:
            self.initial["monthly_price"] = current.price_cents / 100
            self.initial["effective_from"] = current.effective_from
            self.initial["included_items"] = "\n".join(current.entitlements.order_by("display_order").values_list("name", flat=True))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_public") and cleaned.get("is_active") and not cleaned.get("monthly_price"):
            self.add_error("monthly_price", "Informe um preço para disponibilizar este plano no site e no checkout.")
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        plan = super().save(commit=commit)
        if not self.cleaned_data.get("monthly_price"):
            return plan
        price_cents = int(self.cleaned_data["monthly_price"] * 100)
        effective_from = self.cleaned_data.get("effective_from") or timezone.now()
        current = plan.versions.filter(retired_at__isnull=True).order_by("-version").first()
        if not current or current.price_cents != price_cents:
            if current:
                current.retired_at = effective_from
                current.save(update_fields=["retired_at", "updated_at"])
            current = PlanVersion.objects.create(plan=plan, version=(plan.versions.aggregate(max_version=models.Max("version"))["max_version"] or 0) + 1, price_cents=price_cents, effective_from=effective_from, installation_fee_cents=plan.installation_fee_cents)
        items = [line.strip() for line in self.cleaned_data.get("included_items", "").splitlines() if line.strip()]
        for position, name in enumerate(items):
            PlanEntitlement.objects.update_or_create(plan_version=current, benefit_type=f"item-{position + 1}", defaults={"name": name, "unlimited": False, "display_order": position})
        return plan


class EmployeeForm(OperationalModelForm):
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ("full_name", "email", "phone", "is_staff", "is_active")

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.instance.pk and not password:
            raise forms.ValidationError("Defina uma senha inicial.")
        if password:
            validate_password(password, self.instance)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class ClientOnboardingForm(forms.Form):
    full_name = forms.CharField(label="Nome completo", max_length=180)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    user_tax_id = forms.CharField(label="CPF", max_length=14, required=False)
    birth_date = forms.DateField(label="Data de nascimento", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, required=False, help_text="Obrigatória apenas para um novo usuário.")
    user_is_active = forms.BooleanField(label="Usuário ativo", required=False, initial=True)
    organization_name = forms.CharField(label="Nome da organização", max_length=180)
    organization_slug = forms.SlugField(label="Identificador da organização")
    tax_id = forms.CharField(label="CPF/CNPJ", max_length=30, required=False)
    street = forms.CharField(label="Rua", max_length=180, required=False)
    number = forms.CharField(label="Número", max_length=30, required=False)
    complement = forms.CharField(label="Complemento", max_length=120, required=False)
    district = forms.CharField(label="Bairro", max_length=100, required=False)
    city = forms.CharField(label="Cidade", max_length=100, required=False)
    state = forms.CharField(label="UF", max_length=2, required=False)
    postal_code = forms.CharField(label="CEP", max_length=12, required=False)
    property_type = forms.ChoiceField(label="Tipo do imóvel", choices=(("", "Selecione"), *Address.PropertyType.choices), required=False)
    floor = forms.CharField(label="Andar", max_length=20, required=False)
    has_elevator = forms.NullBooleanField(label="Possui elevador?", required=False)
    has_doorman = forms.NullBooleanField(label="Possui portaria?", required=False)
    access_instructions = forms.CharField(label="Instruções de acesso", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    access_notes = forms.CharField(label="Observações de acesso", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    condominium_restrictions = forms.CharField(label="Restrições", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    plan_version = forms.ModelChoiceField(label="Assinatura inicial", queryset=PlanVersion.objects.none(), required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.fields["plan_version"].queryset = get_available_plan_versions()
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control")
        if instance and not self.is_bound:
            member = instance.memberships.filter(is_active=True, role=Membership.Role.OWNER).select_related("organization").first()
            org = member.organization if member else None
            address = org.addresses.first() if org else None
            self.initial.update({"full_name": instance.full_name, "email": instance.email, "phone": instance.phone, "user_tax_id": instance.tax_id, "birth_date": instance.birth_date, "user_is_active": instance.is_active})
            if org:
                self.initial.update({"organization_name": org.name, "organization_slug": org.slug, "tax_id": org.tax_id})
            if address:
                self.initial.update({name: getattr(address, name) for name in ("street", "number", "complement", "district", "city", "state", "postal_code", "property_type", "floor", "has_elevator", "has_doorman", "access_instructions", "access_notes", "condominium_restrictions")})

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        existing = User.objects.filter(email=email).exclude(pk=self.instance.pk if self.instance else None)
        if existing.exists():
            raise forms.ValidationError("Já existe um usuário com este e-mail.")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if not self.instance and not password:
            raise forms.ValidationError("Defina uma senha inicial para o novo cliente.")
        if password:
            validate_password(password, self.instance)
        return password

    def clean(self):
        cleaned = super().clean()
        slug = cleaned.get("organization_slug")
        current_org_id = None
        if self.instance:
            membership = self.instance.memberships.filter(role=Membership.Role.OWNER).first()
            current_org_id = membership.organization_id if membership else None
        if slug and Organization.objects.filter(slug=slug).exclude(pk=current_org_id).exists():
            self.add_error("organization_slug", "Já existe uma organização com este identificador.")
        address_values = [cleaned.get(name) for name in ("street", "city", "state", "postal_code")]
        if any(address_values) and not all(address_values):
            raise forms.ValidationError("Para cadastrar o endereço, informe rua, cidade, UF e CEP.")
        return cleaned

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = self.instance or User()
        user.full_name, user.email, user.phone, user.tax_id, user.birth_date, user.is_active = data["full_name"], data["email"], data["phone"], data["user_tax_id"], data["birth_date"], data["user_is_active"]
        if data.get("password"):
            user.set_password(data["password"])
        user.save()
        membership = user.memberships.filter(role=Membership.Role.OWNER).select_related("organization").first()
        org = membership.organization if membership else Organization()
        org.name, org.slug, org.tax_id, org.is_active = data["organization_name"], data["organization_slug"], data["tax_id"], True
        org.save()
        Membership.objects.update_or_create(user=user, organization=org, defaults={"role": Membership.Role.OWNER, "is_active": True})
        if data.get("street"):
            address_fields = ("street", "number", "complement", "district", "city", "state", "postal_code", "property_type", "floor", "has_elevator", "has_doorman", "access_instructions", "access_notes", "condominium_restrictions")
            Address.objects.update_or_create(organization=org, label="Principal", defaults={name: data.get(name, "") for name in address_fields})
        if data.get("plan_version") and not Subscription.objects.filter(organization=org, status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).exists():
            from django.utils import timezone
            from datetime import timedelta
            Subscription.objects.create(organization=org, plan_version=data["plan_version"], status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30), provider="manual")
        return user
