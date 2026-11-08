from django.contrib.gis import admin

from .models import Site


@admin.register(Site)
class SiteAdmin(admin.GISModelAdmin):
    list_display = ("name", "organisation", "kind", "status", "progress", "is_public")
    list_filter = ("status", "kind", "is_public", "organisation")
    search_fields = ("name", "owner_name")
    gis_widget_kwargs = {"attrs": {"default_lon": 7.4, "default_lat": 9.07, "default_zoom": 11}}