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
