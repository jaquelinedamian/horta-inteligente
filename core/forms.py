from django import forms
from django.contrib.auth.forms import UserCreationForm
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.models import Address, User
from devices.models import IrrigationSchedule, LightingSchedule
from operations.models import SupportTicket, WorkOrder

DAY_CHOICES = tuple(enumerate(("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")))
PUMP_DURATION_CHOICES = (
    (5, "5 segundos"), (10, "10 segundos"), (15, "15 segundos"),
    (20, "20 segundos"), (30, "30 segundos"), (45, "45 segundos"),
    (60, "1 minuto"), (90, "1 min 30 s"), (120, "2 minutos"),
    (180, "3 minutos"), (300, "5 minutos"),
)
MONITORING_INTERVAL_CHOICES = (
    (15, "15 minutos"), (30, "30 minutos"), (60, "1 hora"),
    (120, "2 horas"), (180, "3 horas"), (240, "4 horas"),
    (360, "6 horas"), (480, "8 horas"), (720, "12 horas"),
    (1440, "24 horas"),
)
LIGHT_DURATION_CHOICES = (
    (15, "15 min"), (30, "30 min"), (45, "45 min"), (60, "1 h"),
    (120, "2 h"), (180, "3 h"), (240, "4 h"), (300, "5 h"),
    (360, "6 h"), (480, "8 h"), (600, "10 h"), (720, "12 h"),
    (960, "16 h"), (1080, "18 h"), (1200, "20 h"), (1440, "24 h"),
)


def _add_current_choice(form, name, label_suffix="configuração atual"):
    """Keep a saved or submitted valid value selectable even outside UX presets."""
    field = form.fields[name]
    raw = form.data.get(form.add_prefix(name)) if form.is_bound else form.initial.get(name)
    if raw in (None, ""):
        return
    current_values = {str(value) for value, _ in field.choices}
    if str(raw) not in current_values:
        field.choices = (*field.choices, (raw, f"{raw} ({label_suffix})"))


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                field.widget.attrs["class"] = "weekday-checks"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
                field.widget.attrs["role"] = "switch"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"


class SignupForm(StyledFormMixin, UserCreationForm):
    class Meta:
        model = User
        fields = ("full_name", "email", "phone")


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("full_name", "email", "phone")


class SupportTicketForm(StyledFormMixin, forms.ModelForm):
    category = forms.ChoiceField(choices=[(x, x) for x in ("Equipamento", "Planta", "Irrigação", "Iluminação", "Cobrança", "Solicitar visita", "Outro")])
    class Meta:
        model = SupportTicket
        fields = ("category", "subject", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}


class LightingScheduleForm(StyledFormMixin, forms.ModelForm):
    duration_minutes = forms.TypedChoiceField(
        label="Tempo ligada", choices=LIGHT_DURATION_CHOICES, coerce=int,
        help_text="Escolha por quanto tempo a iluminação permanecerá ligada.",
    )
    days_of_week = forms.TypedMultipleChoiceField(
        label="Dias da semana", choices=DAY_CHOICES,
        coerce=int, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = LightingSchedule
        fields = ("start_time", "duration_minutes", "days_of_week", "enabled")
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.start_time and self.instance.end_time:
            start = self.instance.start_time.hour * 60 + self.instance.start_time.minute
            end = self.instance.end_time.hour * 60 + self.instance.end_time.minute
            self.initial.setdefault("duration_minutes", (end - start) % 1440 or 1440)
        _add_current_choice(self, "duration_minutes", "minutos · configuração atual")
        self.fields["start_time"].label = "Horário de início"
        self.fields["enabled"].label = "Ativo"

    def save(self, commit=True):
        item = super().save(commit=False)
        base = datetime.combine(timezone.localdate(), self.cleaned_data["start_time"])
        item.end_time = (base + timedelta(minutes=self.cleaned_data["duration_minutes"])).time()
        if commit:
            item.save()
        return item


class IrrigationScheduleForm(StyledFormMixin, forms.ModelForm):
    duration_seconds = forms.TypedChoiceField(
        label="Duração da bomba", choices=PUMP_DURATION_CHOICES, coerce=int,
    )
    days_of_week = forms.TypedMultipleChoiceField(
        label="Dias da semana", choices=DAY_CHOICES,
        coerce=int, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = IrrigationSchedule
        fields = ("start_time", "duration_seconds", "days_of_week", "enabled")
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _add_current_choice(self, "duration_seconds", "segundos · configuração atual")
        self.fields["start_time"].label = "Horário de início"
        self.fields["enabled"].label = "Ativo"

    def clean_duration_seconds(self):
        value = self.cleaned_data["duration_seconds"]
        if not 1 <= value <= 300:
            raise forms.ValidationError("Use uma duração entre 1 e 300 segundos.")
        return value


class SoilCalibrationForm(StyledFormMixin, forms.Form):
    dry_raw = forms.IntegerField(label="Valor seco (RAW)", min_value=0, max_value=1023)
    wet_raw = forms.IntegerField(label="Valor molhado (RAW)", min_value=0, max_value=1023)

    def clean(self):
        data = super().clean()
        if data.get("dry_raw") == data.get("wet_raw"):
            raise forms.ValidationError("Os valores seco e molhado devem ser diferentes.")
        return data


class GardenOperationalConfigurationForm(StyledFormMixin, forms.Form):
    light_hours = forms.TypedChoiceField(
        label="Horas de luz por dia",
        choices=tuple((value, f"{value} h") for value in range(1, 19)),
        coerce=Decimal,
    )
    irrigation_frequency_count = forms.TypedChoiceField(
        label="Irrigações",
        choices=tuple((value, f"{value} vez" if value == 1 else f"{value} vezes") for value in range(7)),
        coerce=int,
    )
    irrigation_frequency_period = forms.ChoiceField(label="Período", choices=(("day", "Diário"), ("week", "Semanal")))
    pump_duration_seconds = forms.TypedChoiceField(
        label="Duração da bomba", choices=PUMP_DURATION_CHOICES, coerce=int,
    )
    photos_per_day = forms.TypedChoiceField(
        label="Fotos por dia",
        choices=((value, f"{value} foto{'s' if value > 1 else ''}/dia") for value in range(1, 5)),
        coerce=int,
    )
    monitoring_interval_minutes = forms.TypedChoiceField(
        label="Intervalo de monitoramento", choices=MONITORING_INTERVAL_CHOICES, coerce=int,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _add_current_choice(self, "light_hours", "h · configuração atual")
        _add_current_choice(self, "irrigation_frequency_count", "vezes · configuração atual")
        _add_current_choice(self, "pump_duration_seconds", "segundos · configuração atual")
        _add_current_choice(self, "monitoring_interval_minutes", "minutos · configuração atual")
        help_texts = {
            "light_hours": "Permitido: 1 a 18 horas por dia.",
            "irrigation_frequency_count": "Permitido: 0 a 6 vezes no período escolhido.",
            "irrigation_frequency_period": "Escolha se a frequência é diária ou semanal.",
            "pump_duration_seconds": "Escolha uma duração segura, de 5 segundos a 5 minutos.",
            "photos_per_day": "Máximo de 4 fotografias por dia.",
            "monitoring_interval_minutes": "Escolha a frequência usando uma unidade de tempo amigável.",
        }
        for name, help_text in help_texts.items():
            self.fields[name].help_text = help_text

    def clean_light_hours(self):
        value = self.cleaned_data["light_hours"]
        if not Decimal("1") <= value <= Decimal("18"):
            raise forms.ValidationError("Use entre 1 e 18 horas de luz por dia.")
        return value

    def clean_irrigation_frequency_count(self):
        value = self.cleaned_data["irrigation_frequency_count"]
        if not 0 <= value <= 6:
            raise forms.ValidationError("Use entre 0 e 6 irrigações.")
        return value

    def clean_pump_duration_seconds(self):
        value = self.cleaned_data["pump_duration_seconds"]
        if not 1 <= value <= 300:
            raise forms.ValidationError("Use uma duração entre 1 e 300 segundos.")
        return value

    def clean_monitoring_interval_minutes(self):
        value = self.cleaned_data["monitoring_interval_minutes"]
        if not 15 <= value <= 1440:
            raise forms.ValidationError("Use um intervalo entre 15 minutos e 24 horas.")
        return value


class WorkOrderForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = ("organization", "garden", "module", "device", "kind", "title", "description", "priority", "scheduled_for")
        widgets = {"scheduled_for": forms.DateTimeInput(attrs={"type": "datetime-local"}), "description": forms.Textarea(attrs={"rows": 3})}


class CheckoutAddressForm(StyledFormMixin, forms.Form):
    street = forms.CharField(label="Rua")
    number = forms.CharField(label="Número")
    city = forms.CharField(label="Cidade")
    state = forms.CharField(label="UF", max_length=2)
    postal_code = forms.CharField(label="CEP")


class InstallationSurveyForm(StyledFormMixin, forms.Form):
    socket_nearby = forms.BooleanField(label="Existe tomada próxima?", required=False)
    wifi_available = forms.BooleanField(label="Wi-Fi disponível?", required=False)
    pets = forms.BooleanField(label="Há animais no local?", required=False)
    children = forms.BooleanField(label="Há crianças no local?", required=False)
    sunlight = forms.ChoiceField(label="Incidência solar", choices=(("low", "Baixa"), ("medium", "Média"), ("high", "Alta")))
    restrictions = forms.CharField(label="Restrições do condomínio", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class InstallationDateForm(StyledFormMixin, forms.Form):
    scheduled_for = forms.DateTimeField(label="Data e horário", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    def clean_scheduled_for(self):
        value = self.cleaned_data["scheduled_for"]
        if value <= timezone.now():
            raise forms.ValidationError("Escolha uma data futura para a instalação.")
        return value
