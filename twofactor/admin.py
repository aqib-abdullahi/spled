from django.contrib import admin

from .models import TwoFactor
from .services import disable


@admin.register(TwoFactor)
class TwoFactorAdmin(admin.ModelAdmin):
    """Platform staff can switch a person's two-step verification off here
    (lost phone and lost backup codes). The secret is never shown."""

    list_display = ("user", "confirmed_at", "created_at")
    fields = ("user", "confirmed_at", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        disable(obj.user)

    def delete_queryset(self, request, queryset):
        for obj in list(queryset):
            disable(obj.user)