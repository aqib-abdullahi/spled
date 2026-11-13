from django.contrib import admin

from .models import ShareLink


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = (
        "label", "site", "created_by", "created_at", "expires_at", "revoked_at", "view_count",
    )
    list_filter = ("revoked_at",)
    exclude = ("token_hash", "password_hash")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False