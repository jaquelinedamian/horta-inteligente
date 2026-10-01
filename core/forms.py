from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from accounts.models import Address, User
from devices.models import LightingSchedule
from operations.models import SupportTicket, WorkOrder


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"


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
    class Meta:
        model = LightingSchedule
        fields = ("start_time", "end_time", "enabled")
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}


class GardenOperationalConfigurationForm(StyledFormMixin, forms.Form):
    light_hours = forms.DecimalField(label="Horas de luz por dia", min_value=1, max_value=18, decimal_places=1)
    irrigation_frequency_count = forms.IntegerField(label="Irrigações", min_value=0, max_value=6)
    irrigation_frequency_period = forms.ChoiceField(label="Período", choices=(("day", "Dia"), ("week", "Semana")))
    pump_duration_seconds = forms.IntegerField(label="Duração da bomba (segundos)", min_value=1, max_value=300)
    photos_per_day = forms.TypedChoiceField(
        label="Fotos por dia",
        choices=((value, f"{value} foto{'s' if value > 1 else ''}/dia") for value in range(1, 5)),
        coerce=int,
    )
    monitoring_interval_minutes = forms.IntegerField(label="Intervalo de monitoramento (minutos)", min_value=15, max_value=1440)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        help_texts = {
            "light_hours": "Permitido: 1 a 18 horas por dia.",
            "irrigation_frequency_count": "Permitido: 0 a 6 vezes no período escolhido.",
            "irrigation_frequency_period": "Escolha se a frequência é diária ou semanal.",
            "pump_duration_seconds": "Permitido: 1 a 300 segundos.",
            "photos_per_day": "Máximo de 4 fotografias por dia.",
            "monitoring_interval_minutes": "Permitido: 15 a 1.440 minutos.",
        }
        for name, help_text in help_texts.items():
            self.fields[name].help_text = help_text


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
