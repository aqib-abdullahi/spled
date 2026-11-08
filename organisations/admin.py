from django.contrib import admin

from .models import Membership, Organisation


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "verification", "created_at")
    list_filter = ("kind", "verification")
    search_fields = ("name",)
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "role")
    list_filter = ("role",)