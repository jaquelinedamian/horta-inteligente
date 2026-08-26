from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.forms import modelform_factory

from accounts.models import Address, Membership, Organization, User
from devices.models import Channel
from subscriptions.models import PlanVersion, Subscription


LABELS = {
    "organization": "Organização", "plan_version": "Plano / versão", "module_type": "Tipo de módulo",
    "serial_number": "Número de série", "common_name": "Nome comum", "scientific_name": "Nome científico",
    "is_active": "Ativo", "is_available": "Disponível", "current_period_start": "Início do período",
    "current_period_end": "Fim do período", "scheduled_start": "Início agendado", "scheduled_end": "Fim agendado",
    "scheduled_for": "Data agendada", "opened_by": "Aberto por", "performed_by": "Executado por",
    "minimum_quantity": "Quantidade mínima", "price_cents": "Preço em centavos", "interval_days": "Periodicidade em dias",
}


class OperationalModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.label = LABELS.get(name, field.label)
            field.widget.attrs.setdefault("class", "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control")
            if isinstance(field.widget, forms.DateTimeInput):
                field.widget.input_type = "datetime-local"
                field.widget.format = "%Y-%m-%dT%H:%M"

    def clean(self):
        cleaned = super().clean()
        organization = cleaned.get("organization")
        for name in ("garden", "module", "device"):
            related = cleaned.get(name)
            if organization and related and related.organization_id != organization.id:
                self.add_error(name, "Selecione um registro pertencente à organização escolhida.")
        channel = cleaned.get("channel")
        if organization and channel and channel.device.organization_id != organization.id:
            self.add_error("channel", "O canal pertence a outra organização.")
        actuator = cleaned.get("actuator")
        if actuator and actuator.kind != Channel.Kind.ACTUATOR:
            self.add_error("actuator", "Selecione um canal do tipo atuador.")
        return cleaned


def resource_form_class(resource):
    if resource.model is User:
        return EmployeeForm
    return modelform_factory(resource.model, form=OperationalModelForm, fields=resource.fields)


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
    password = forms.CharField(label="Senha inicial", widget=forms.PasswordInput, required=False, help_text="Obrigatória apenas para um novo usuário.")
    user_is_active = forms.BooleanField(label="Usuário ativo", required=False, initial=True)
    organization_name = forms.CharField(label="Nome da organização", max_length=180)
    organization_slug = forms.SlugField(label="Identificador da organização")
    tax_id = forms.CharField(label="CPF/CNPJ", max_length=30, required=False)
    street = forms.CharField(label="Rua", max_length=180, required=False)
    number = forms.CharField(label="Número", max_length=30, required=False)
    city = forms.CharField(label="Cidade", max_length=100, required=False)
    state = forms.CharField(label="UF", max_length=2, required=False)
    postal_code = forms.CharField(label="CEP", max_length=12, required=False)
    plan_version = forms.ModelChoiceField(label="Assinatura inicial", queryset=PlanVersion.objects.none(), required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        self.fields["plan_version"].queryset = PlanVersion.objects.filter(plan__is_active=True, retired_at__isnull=True).select_related("plan")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control")
        if instance and not self.is_bound:
            member = instance.memberships.filter(is_active=True, role=Membership.Role.OWNER).select_related("organization").first()
            org = member.organization if member else None
            address = org.addresses.first() if org else None
            self.initial.update({"full_name": instance.full_name, "email": instance.email, "phone": instance.phone, "user_is_active": instance.is_active})
            if org:
                self.initial.update({"organization_name": org.name, "organization_slug": org.slug, "tax_id": org.tax_id})
            if address:
                self.initial.update({name: getattr(address, name) for name in ("street", "number", "city", "state", "postal_code")})

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
        user.full_name, user.email, user.phone, user.is_active = data["full_name"], data["email"], data["phone"], data["user_is_active"]
        if data.get("password"):
            user.set_password(data["password"])
        user.save()
        membership = user.memberships.filter(role=Membership.Role.OWNER).select_related("organization").first()
        org = membership.organization if membership else Organization()
        org.name, org.slug, org.tax_id, org.is_active = data["organization_name"], data["organization_slug"], data["tax_id"], True
        org.save()
        Membership.objects.update_or_create(user=user, organization=org, defaults={"role": Membership.Role.OWNER, "is_active": True})
        if data.get("street"):
            Address.objects.update_or_create(organization=org, label="Principal", defaults={name: data.get(name, "") for name in ("street", "number", "city", "state", "postal_code")})
        if data.get("plan_version") and not Subscription.objects.filter(organization=org, status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).exists():
            from django.utils import timezone
            from datetime import timedelta
            Subscription.objects.create(organization=org, plan_version=data["plan_version"], status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30), provider="manual")
        return user
