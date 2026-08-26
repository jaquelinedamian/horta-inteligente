from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Address, Invitation, Membership, Organization, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "full_name", "is_staff", "is_active")
    fieldsets = ((None, {"fields": ("email", "password")}),) + UserAdmin.fieldsets[2:]
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "full_name", "password1", "password2")}),)


admin.site.register(Organization)
admin.site.register(Membership)
admin.site.register(Address)
admin.site.register(Invitation)
