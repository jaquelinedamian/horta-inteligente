from io import BytesIO

from PIL import Image, ImageOps
from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone

from subscriptions.models import Plan, PlanEntitlement, PlanVersion


class PlanAdminForm(forms.ModelForm):
    monthly_price = forms.DecimalField(label="Mensalidade (R$)", min_value=0.01, max_digits=10, decimal_places=2)
    installation_fee = forms.DecimalField(label="Taxa de instalação (R$)", min_value=0, max_digits=10, decimal_places=2, required=False)
    effective_from = forms.DateTimeField(label="Início da vigência", required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    image = forms.ImageField(label="Imagem do plano", required=False, help_text="JPG, PNG ou WebP; máximo de 5 MB.")
    remove_image = forms.BooleanField(label="Remover imagem atual", required=False)

    class Meta:
        model = Plan
        fields = ("name", "commercial_title", "short_copy", "description", "garden_model", "code", "display_order", "is_active", "is_public", "is_featured")
        labels = {
            "name": "Nome do plano", "commercial_title": "Título comercial", "short_copy": "Descrição curta",
            "description": "Descrição completa", "garden_model": "Modelo de horta", "code": "Código",
            "display_order": "Ordem de exibição", "installation_fee_cents": "Taxa de instalação (centavos)",
            "is_active": "Ativo", "is_public": "Visível no site", "is_featured": "Plano em destaque",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "short_copy": forms.Textarea(attrs={"rows": 2, "maxlength": 256})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.versions.filter(retired_at__isnull=True).order_by("-version").first() if self.instance.pk else None
        if current and not self.is_bound:
            self.initial.update(monthly_price=current.price_cents / 100, effective_from=current.effective_from)
        if self.instance.pk and not self.is_bound:
            self.initial["installation_fee"] = self.instance.installation_fee_cents / 100
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.ClearableFileInput)):
                field.widget.attrs.setdefault("class", "form-control")

    def clean_short_copy(self):
        value = self.cleaned_data.get("short_copy", "")
        if len(value) > 256:
            raise forms.ValidationError("Use no máximo 256 caracteres.")
        return value

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
        plan = super().save(commit=False)
        plan.installation_fee_cents = int((self.cleaned_data.get("installation_fee") or 0) * 100)
        if commit:
            plan.save()
            self.save_m2m()
        return plan

    def save_image(self, plan):
        if self.cleaned_data.get("remove_image"):
            plan.image_data = None
            plan.image_content_type = ""
            plan.image_filename = ""
            plan.image_url = ""
        image = self.cleaned_data.get("image")
        if image:
            image.seek(0)
            with Image.open(image) as source:
                optimized = ImageOps.exif_transpose(source).convert("RGB")
                optimized.thumbnail((1400, 1000), Image.Resampling.LANCZOS)
                output = BytesIO()
                optimized.save(output, "WEBP", quality=82, method=6)
            plan.image_data = output.getvalue()
            plan.image_content_type = "image/webp"
            plan.image_filename = f"{plan.code}.webp"
            plan.image_url = ""
        plan.save()

    def create_version(self, plan, source=None):
        effective = self.cleaned_data.get("effective_from") or timezone.now()
        if source:
            source.retired_at = effective
            source.save(update_fields=["retired_at", "updated_at"])
        version = (plan.versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
        return PlanVersion.objects.create(
            plan=plan, version=version, price_cents=int(self.cleaned_data["monthly_price"] * 100),
            effective_from=effective, installation_fee_cents=plan.installation_fee_cents,
            commercial_snapshot={"name": plan.name, "title": plan.commercial_title, "short_copy": plan.short_copy},
        )


class PlanEntitlementForm(forms.ModelForm):
    class Meta:
        model = PlanEntitlement
        fields = ("name", "icon", "description", "quantity", "unit", "display_order", "is_included", "is_featured")
        labels = {"name": "Benefício", "icon": "Ícone", "description": "Descrição", "quantity": "Quantidade", "unit": "Unidade", "display_order": "Ordem", "is_included": "Incluído", "is_featured": "Destaque"}
        widgets = {"description": forms.Textarea(attrs={"rows": 2}), "icon": forms.TextInput(attrs={"placeholder": "Ex.: bi-tools"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")


PlanEntitlementFormSet = inlineformset_factory(
    PlanVersion, PlanEntitlement, form=PlanEntitlementForm,
    extra=1, can_delete=True,
)
