from django import forms
from django.conf import settings
from collections.abc import Mapping
from decimal import Decimal
from django.contrib.auth.password_validation import validate_password
from django.db import models, transaction
from django.forms import inlineformset_factory, modelform_factory
from django.template.loader import render_to_string
from django.core.exceptions import FieldDoesNotExist
from django.utils import timezone
from django.utils.text import slugify
from django.utils.safestring import mark_safe

from accounts.models import Address, Membership, Organization, User
from devices.models import Channel, Device
from subscriptions.models import Plan, PlanEntitlement, PlanVersion, Subscription
from subscriptions.selectors import get_available_plan_versions
from crops.models import Crop, CropLightingSchedule, PlantingCycle
from crops.selectors import get_available_cultivars
from gardens.models import Garden, GardenModel, GardenModelFeature, GardenModule, ModuleInstallation
from operations.models import Visit
from core.forms import MONITORING_INTERVAL_CHOICES, PUMP_DURATION_CHOICES


LIGHT_HOUR_CHOICES = tuple((value, f"{value} h") for value in range(1, 19))
IRRIGATION_COUNT_CHOICES = tuple(
    (value, f"{value} vez" if value == 1 else f"{value} vezes") for value in range(7)
)
PHOTO_COUNT_CHOICES = tuple(
    (value, f"{value} foto/dia" if value == 1 else f"{value} fotos/dia") for value in range(1, 5)
)


def _optional_choices(choices):
    return (("", "Usar padrão existente"), *choices)


def _keep_instance_choice(form, name, value, suffix):
    if value in (None, ""):
        return
    field = form.fields[name]
    if str(value) not in {str(key) for key, _ in field.choices}:
        field.choices = (*field.choices, (value, f"{value} ({suffix})"))


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
    "kind": "Tipo do dispositivo",
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
        preset_fields = {
            "light_hours_per_day": ("Horas de luz por dia", _optional_choices(LIGHT_HOUR_CHOICES), Decimal),
            "irrigation_frequency_count": ("Irrigações", _optional_choices(IRRIGATION_COUNT_CHOICES), int),
            "pump_duration_seconds": ("Duração da bomba", _optional_choices(PUMP_DURATION_CHOICES), int),
            "photos_per_day": ("Fotos por dia", PHOTO_COUNT_CHOICES, int),
            "monitoring_interval_minutes": ("Intervalo de monitoramento", MONITORING_INTERVAL_CHOICES, int),
        }
        for name, (label, choices, coerce) in preset_fields.items():
            if name not in self.fields:
                continue
            previous = self.fields[name]
            self.fields[name] = forms.TypedChoiceField(
                label=label,
                choices=choices,
                coerce=coerce,
                required=previous.required,
                empty_value=None,
                help_text=previous.help_text,
            )
            current = getattr(self.instance, name, None) if self.instance and self.instance.pk else self.initial.get(name)
            _keep_instance_choice(self, name, current, "configuração atual")
        if "plan_version" in self.fields:
            available = get_available_plan_versions()
            selected_id = self.data.get(self.add_prefix("plan_version")) if self.is_bound else getattr(self.instance, "plan_version_id", None)
            if selected_id:
                available = (available | PlanVersion.objects.filter(pk=selected_id)).distinct()
            self.fields["plan_version"].queryset = available
        if "cultivar" in self.fields:
            self.fields["cultivar"].queryset = get_available_cultivars()
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "weekday-checks"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
                field.widget.attrs["role"] = "switch"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs.setdefault("class", "form-control")
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


class CropAvailabilitySwitch(forms.CheckboxInput):
    template_name = "widgets/crop_availability_switch.html"

    def render(self, name, value, attrs=None, renderer=None):
        return mark_safe(render_to_string(self.template_name, self.get_context(name, value, attrs)))


class GardenModelForm(OperationalModelForm):
    image = forms.ImageField(label="Imagem principal", required=False, help_text="JPG, PNG ou WebP; máximo de 5 MB.")
    remove_image = forms.BooleanField(label="Remover imagem atual", required=False)

    class Meta:
        model = GardenModel
        fields = ("name", "code", "description", "capacity", "reservoir_liters", "height_cm", "width_cm", "depth_cm", "module_count", "light_hours_per_day", "irrigation_frequency_count", "irrigation_frequency_period", "pump_duration_seconds", "photos_per_day", "monitoring_interval_minutes", "is_active")
        labels = {
            "capacity": "Quantidade máxima de plantas", "reservoir_liters": "Capacidade do reservatório (L)",
            "height_cm": "Altura (cm)", "width_cm": "Largura (cm)", "depth_cm": "Profundidade (cm)",
            "module_count": "Quantidade de módulos",
        }
        widgets = {
            "reservoir_liters": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "height_cm": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "width_cm": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "depth_cm": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > 5 * 1024 * 1024:
            raise forms.ValidationError("A imagem deve ter no máximo 5 MB.")
        if image and image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Envie uma imagem JPG, PNG ou WebP.")
        return image

    def save(self, commit=True):
        from io import BytesIO
        from PIL import Image, ImageOps
        model = super().save(commit=False)
        if self.cleaned_data.get("remove_image"):
            model.image_data, model.image_content_type, model.image_filename = None, "", ""
        image = self.cleaned_data.get("image")
        if image:
            image.seek(0)
            with Image.open(image) as source:
                optimized = ImageOps.exif_transpose(source).convert("RGB")
                optimized.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
                output = BytesIO(); optimized.save(output, "WEBP", quality=82, method=6)
            model.image_data = output.getvalue()
            model.image_content_type = "image/webp"
            model.image_filename = f"{model.code or 'modelo'}.webp"
        if commit:
            model.save(); self.save_m2m()
            if not model.physical_features.exists():
                dimensions = " × ".join(str(value).rstrip("0").rstrip(".") for value in (model.height_cm, model.width_cm, model.depth_cm) if value is not None)
                defaults = (
                    ("Quantidade de mudas", model.capacity, "mudas", "bi-flower1"),
                    ("Capacidade do reservatório", model.reservoir_liters, "L", "bi-droplet"),
                    ("Dimensões", dimensions, "cm", "bi-rulers"),
                    ("Quantidade de módulos", model.module_count, "módulos", "bi-boxes"),
                )
                GardenModelFeature.objects.bulk_create([
                    GardenModelFeature(garden_model=model, name=name, value=str(value), unit=unit, icon=icon, display_order=order)
                    for order, (name, value, unit, icon) in enumerate(defaults) if value not in (None, "")
                ])
        return model


class GardenModelFeatureForm(OperationalModelForm):
    class Meta:
        model = GardenModelFeature
        fields = ("name", "value", "unit", "icon", "display_order", "is_visible")
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ex.: Altura"}),
            "value": forms.TextInput(attrs={"placeholder": "Ex.: 85"}),
            "unit": forms.TextInput(attrs={"placeholder": "Ex.: cm"}),
            "display_order": forms.NumberInput(attrs={"min": 0}),
        }

    def clean_value(self):
        return self.cleaned_data["value"].strip()


GardenModelFeatureFormSet = inlineformset_factory(
    GardenModel, GardenModelFeature, form=GardenModelFeatureForm,
    extra=0, can_delete=True, min_num=0, validate_min=False,
)


def resource_form_class(resource):
    if resource.model is User:
        return EmployeeForm
    if resource.model is Plan:
        return CommercialPlanForm
    if resource.model is GardenModel:
        return GardenModelForm
    if resource.model is Crop:
        return CropForm
    if resource.model is CropLightingSchedule:
        return CropLightingScheduleForm
    if resource.model is Visit:
        return VisitForm
    if resource.model is Garden:
        return GardenForm
    if resource.model is Device:
        return DeviceForm
    return modelform_factory(resource.model, form=OperationalModelForm, fields=resource.fields)


class CropLightingScheduleForm(OperationalModelForm):
    duration_hours = forms.DecimalField(
        label="Horas de luz por dia", min_value=1, max_value=24,
        max_digits=4, decimal_places=1,
        widget=forms.NumberInput(attrs={"min": "1", "max": "24", "step": "0.5"}),
        help_text="Informe uma duração entre 1 e 24 horas.",
    )

    class Meta:
        model = CropLightingSchedule
        fields = ("crop", "start_time", "duration_hours", "enabled")
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crop"].label = "Espécie"
        self.fields["crop"].queryset = Crop.objects.filter(code__in=("alface", "tomilho", "coentro")).order_by("common_name")
        self.fields["start_time"].label = "Horário de início da iluminação"
        self.fields["enabled"].label = "Ativo"
        if self.instance and self.instance.pk and self.instance.start_time and self.instance.end_time:
            start = self.instance.start_time.hour * 60 + self.instance.start_time.minute
            end = self.instance.end_time.hour * 60 + self.instance.end_time.minute
            self.initial.setdefault("duration_hours", ((end - start) % 1440 or 1440) / 60)
        elif self.instance and self.instance.crop_id and self.instance.crop.light_hours:
            self.initial.setdefault("duration_hours", self.instance.crop.light_hours)
        else:
            self.initial.setdefault("duration_hours", 12)

    def save(self, commit=True):
        from datetime import datetime, timedelta

        schedule = super().save(commit=False)
        start = datetime.combine(timezone.localdate(), self.cleaned_data["start_time"])
        minutes = int(self.cleaned_data["duration_hours"] * 60)
        schedule.end_time = (start + timedelta(minutes=minutes)).time()
        schedule.name = "Iluminação recomendada"
        schedule.days_of_week = list(range(7))
        schedule.timezone = schedule.timezone or settings.TIME_ZONE
        if commit:
            schedule.save()
            if schedule.crop.light_hours != self.cleaned_data["duration_hours"]:
                schedule.crop.light_hours = self.cleaned_data["duration_hours"]
                schedule.crop.save(update_fields=["light_hours", "updated_at"])
        return schedule

    def clean(self):
        from datetime import datetime, timedelta

        cleaned = super().clean()
        start_time = cleaned.get("start_time")
        duration = cleaned.get("duration_hours")
        if start_time is not None and duration is not None:
            start = datetime.combine(timezone.localdate(), start_time)
            self.instance.end_time = (start + timedelta(minutes=int(duration * 60))).time()
        self.instance.name = "Iluminação recomendada"
        self.instance.days_of_week = list(range(7))
        self.instance.timezone = self.instance.timezone or settings.TIME_ZONE
        return cleaned


class DeviceForm(OperationalModelForm):
    class Meta:
        model = Device
        fields = ("organization", "garden", "model", "module", "serial_number", "name", "kind", "status", "firmware_version", "local_ip", "metadata")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # O default do model preserva compatibilidade fora do Admin, mas neste
        # fluxo o operador deve confirmar explicitamente o tipo do equipamento.
        self.fields["kind"].required = True
        self.fields["kind"].label = "Tipo do dispositivo"


class VisitForm(OperationalModelForm):
    class Meta:
        model = Visit
        fields = ("organization", "garden", "work_order", "technician", "visit_type", "scheduled_start", "scheduled_end", "status", "actual_start", "actual_end", "reason", "notes", "conclusion")
        labels = {
            "organization": "Organização", "garden": "Horta", "work_order": "Ordem de serviço",
            "technician": "Técnico responsável", "visit_type": "Tipo de visita",
            "scheduled_start": "Início agendado", "scheduled_end": "Fim agendado",
            "status": "Status", "actual_start": "Início real", "actual_end": "Fim real",
            "reason": "Motivo", "notes": "Observações", "conclusion": "Conclusão",
        }
        widgets = {
            "scheduled_start": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "scheduled_end": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "actual_start": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "actual_end": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["technician"].queryset = User.objects.filter(
            models.Q(employee_role=User.EmployeeRole.TECHNICIAN)
            | models.Q(memberships__is_active=True, memberships__role=Membership.Role.TECHNICIAN),
            is_active=True,
        ).distinct().order_by("full_name", "email")
        organization_id = self.data.get(self.add_prefix("organization")) if self.is_bound else self.instance.organization_id
        if organization_id:
            self.fields["garden"].queryset = Garden.objects.filter(organization_id=organization_id).order_by("name")
            self.fields["work_order"].queryset = self.fields["work_order"].queryset.filter(organization_id=organization_id)


class CropForm(OperationalModelForm):
    image = forms.ImageField(
        label="Fotografia da espécie", required=False,
        help_text="JPG, PNG ou WebP, com no máximo 5 MB. A imagem será redimensionada e otimizada.",
        widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp", "data-crop-image-input": ""}),
    )
    remove_image = forms.BooleanField(label="Remover fotografia atual", required=False)
    light_hours = forms.TypedChoiceField(
        label="Horas de luz por dia",
        choices=_optional_choices(tuple((value, f"{value} h") for value in range(25))),
        coerce=Decimal,
        required=False, empty_value=None,
    )
    irrigation_frequency_count = forms.TypedChoiceField(
        label="Irrigações",
        choices=_optional_choices(IRRIGATION_COUNT_CHOICES),
        coerce=int,
        required=False, empty_value=None,
    )
    irrigation_frequency_period = forms.ChoiceField(
        label="Período", choices=(("day", "Diário"), ("week", "Semanal")), required=False,
    )
    pump_duration_seconds = forms.TypedChoiceField(
        label="Duração da bomba", choices=_optional_choices(PUMP_DURATION_CHOICES),
        coerce=int, required=False, empty_value=None,
    )
    is_available = forms.BooleanField(
        label="", required=False,
        widget=CropAvailabilitySwitch,
    )

    class Meta:
        model = Crop
        fields = (
            "common_name", "scientific_name", "code", "description", "is_available",
            "soil_moisture_requirement", "light_hours", "water_requirement", "drainage_requirement", "cultivation_guidance",
            "ideal_temperature_min", "ideal_temperature_max",
            "irrigation_frequency_count", "irrigation_frequency_period", "pump_duration_seconds",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        self.fields["code"].widget = forms.HiddenInput()
        self.fields["description"].label = "Descrição curta"
        self.fields["description"].widget.attrs["rows"] = 3
        self.fields["cultivation_guidance"].label = "Orientação sobre substrato e drenagem"
        self.fields["soil_moisture_requirement"].label = "Umidade do solo (referência)"
        self.fields["water_requirement"].label = "Necessidade de água"
        self.fields["drainage_requirement"].label = "Drenagem"
        self.fields["is_available"].widget.attrs.update({
            "class": "crop-availability-input",
            "role": "switch",
            "aria-describedby": "crop-availability-description crop-availability-status",
        })
        for name, suffix in (
            ("light_hours", "h · configuração atual"),
            ("irrigation_frequency_count", "vezes · configuração atual"),
            ("pump_duration_seconds", "segundos · configuração atual"),
        ):
            raw = self.data.get(self.add_prefix(name)) if self.is_bound else getattr(self.instance, name, None)
            if raw not in (None, "") and str(raw) not in {str(key) for key, _ in self.fields[name].choices}:
                self.fields[name].choices = (*self.fields[name].choices, (raw, f"{raw} ({suffix})"))

    def clean_is_available(self):
        available = self.cleaned_data["is_available"]
        if self.instance.pk and not available and self.instance.is_available:
            self.active_cycle_count = PlantingCycle.objects.filter(crop=self.instance, status=PlantingCycle.Status.ACTIVE).count()
        return available

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image:
            return image
        if image.size > 5 * 1024 * 1024:
            raise forms.ValidationError("A imagem deve ter no máximo 5 MB.")
        if image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise forms.ValidationError("Envie uma imagem JPG, PNG ou WebP.")
        return image

    def save(self, commit=True):
        from io import BytesIO
        from PIL import Image, ImageOps

        crop = super().save(commit=False)
        if not crop.code:
            crop.code = slugify(crop.common_name)
        image = self.cleaned_data.get("image")
        if self.cleaned_data.get("remove_image"):
            crop.image_data = None
            crop.image_content_type = ""
            crop.image_filename = ""
            crop.image_url = ""
        if image:
            image.seek(0)
            with Image.open(image) as source:
                optimized = ImageOps.exif_transpose(source)
                if optimized.mode not in ("RGB", "RGBA"):
                    optimized = optimized.convert("RGBA" if "transparency" in optimized.info else "RGB")
                optimized.thumbnail((1200, 900), Image.Resampling.LANCZOS)
                output = BytesIO()
                optimized.save(output, format="WEBP", quality=82, method=6)
            crop.image_data = output.getvalue()
            crop.image_content_type = "image/webp"
            crop.image_filename = f"{crop.code or 'cultura'}.webp"
            crop.image_url = ""
        if commit:
            crop.save()
            self.save_m2m()
        return crop


class CommercialPlanForm(OperationalModelForm):
    monthly_price = forms.DecimalField(label="Preço mensal", max_digits=10, decimal_places=2, min_value=0.01, required=False, help_text="Obrigatório para publicar o plano no site e disponibilizá-lo para novas assinaturas.")
    included_items = forms.CharField(label="Itens incluídos", required=False, widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Um benefício por linha. Ex.: 3 módulos"}), help_text="Cria os benefícios da versão atual do plano.")

    class Meta:
        model = Plan
        fields = ("garden_model", "name", "code", "description", "installation_fee_cents", "is_public", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.versions.filter(retired_at__isnull=True).order_by("-version").first() if self.instance.pk else None
        if current and not self.is_bound:
            self.initial["monthly_price"] = current.price_cents / 100
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
        effective_from = timezone.now()
        current = plan.versions.filter(retired_at__isnull=True).order_by("-version").first()
        if not current or current.price_cents != price_cents:
            if current:
                current.retired_at = effective_from
                current.save(update_fields=["retired_at", "updated_at"])
            current = PlanVersion.objects.create(plan=plan, version=(plan.versions.aggregate(max_version=models.Max("version"))["max_version"] or 0) + 1, price_cents=price_cents, effective_from=effective_from, installation_fee_cents=plan.installation_fee_cents)
        items = [line.strip() for line in self.cleaned_data.get("included_items", "").splitlines() if line.strip()]
        retained_types = []
        for position, name in enumerate(items):
            benefit_type = f"item-{position + 1}"
            retained_types.append(benefit_type)
            PlanEntitlement.objects.update_or_create(plan_version=current, benefit_type=benefit_type, defaults={"name": name, "unlimited": False, "display_order": position})
        current.entitlements.filter(benefit_type__startswith="item-").exclude(benefit_type__in=retained_types).delete()
        return plan


class EmployeeForm(OperationalModelForm):
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = ("full_name", "email", "phone", "employee_role", "is_active")

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


class GardenForm(OperationalModelForm):
    light_hours = forms.TypedChoiceField(
        label="Horas de luz por dia",
        choices=_optional_choices(tuple((value, f"{value} h") for value in range(25))),
        coerce=Decimal, required=False, empty_value=None,
    )
    irrigation_frequency_count = forms.TypedChoiceField(
        label="Irrigações", choices=_optional_choices(IRRIGATION_COUNT_CHOICES),
        coerce=int, required=False, empty_value=None,
    )
    irrigation_frequency_period = forms.ChoiceField(
        label="Período", choices=(("day", "Diário"), ("week", "Semanal")), required=False,
    )
    pump_duration_seconds = forms.TypedChoiceField(
        label="Duração da bomba", choices=_optional_choices(PUMP_DURATION_CHOICES),
        coerce=int, required=False, empty_value=None,
    )

    class Meta:
        model = Garden
        fields = ("organization", "name", "code", "garden_model", "subscription", "address", "status", "primary_technician", "installed_at", "operational_notes", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = self.instance.automation_overrides if self.instance.pk and isinstance(self.instance.automation_overrides, Mapping) else {}
        irrigation = config.get("irrigation", {}) if isinstance(config.get("irrigation"), Mapping) else {}
        lighting = config.get("lighting", {}) if isinstance(config.get("lighting"), Mapping) else {}
        self.initial.setdefault("light_hours", lighting.get("hours_per_day"))
        self.initial.setdefault("irrigation_frequency_count", irrigation.get("frequency_count"))
        self.initial.setdefault("irrigation_frequency_period", irrigation.get("frequency_period"))
        self.initial.setdefault("pump_duration_seconds", irrigation.get("pump_duration_seconds"))
        for name, suffix in (
            ("light_hours", "h · configuração atual"),
            ("irrigation_frequency_count", "vezes · configuração atual"),
            ("pump_duration_seconds", "segundos · configuração atual"),
        ):
            raw = self.data.get(self.add_prefix(name)) if self.is_bound else self.initial.get(name)
            if raw not in (None, "") and str(raw) not in {str(key) for key, _ in self.fields[name].choices}:
                self.fields[name].choices = (*self.fields[name].choices, (raw, f"{raw} ({suffix})"))
        self.fields["primary_technician"].queryset = User.objects.filter(is_active=True, employee_role=User.EmployeeRole.TECHNICIAN)

    def save(self, commit=True):
        garden = super().save(commit=False)
        garden.automation_overrides = {
            **(garden.automation_overrides if isinstance(garden.automation_overrides, Mapping) else {}),
            "lighting": {"hours_per_day": float(self.cleaned_data["light_hours"]) if self.cleaned_data.get("light_hours") is not None else None},
            "irrigation": {
                "frequency_count": self.cleaned_data.get("irrigation_frequency_count"),
                "frequency_period": self.cleaned_data.get("irrigation_frequency_period"),
                "pump_duration_seconds": self.cleaned_data.get("pump_duration_seconds"),
            },
        }
        if commit:
            garden.save()
        return garden


class ClientOnboardingForm(forms.Form):
    full_name = forms.CharField(label="Nome completo", max_length=180)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    user_tax_id = forms.CharField(label="CPF", max_length=14, required=False)
    birth_date = forms.DateField(label="Data de nascimento", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, required=False, help_text="Obrigatória apenas para um novo usuário.")
    user_is_active = forms.BooleanField(
        label="Usuário ativo", required=False, initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "role": "switch"}),
    )
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
