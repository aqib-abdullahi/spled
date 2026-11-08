from django.contrib.gis import admin

from .models import EvidenceEntry, Site


@admin.register(Site)
class SiteAdmin(admin.GISModelAdmin):
    list_display = ("name", "organisation", "kind", "status", "progress", "is_public")
    list_filter = ("status", "kind", "is_public", "organisation")
    search_fields = ("name", "owner_name")
    gis_widget_kwargs = {
        "attrs": {"default_lon": 7.4, "default_lat": 9.07, "default_zoom": 11}
    }


@admin.register(EvidenceEntry)
class EvidenceEntryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "site", "kind", "author", "verified_on_site")
    list_filter = ("kind", "verified_on_site")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False