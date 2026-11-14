from django.contrib import admin
from django.urls import include, path

from twofactor.admin_gate import admin_login

urlpatterns = [
    path("admin/login/", admin_login, name="admin_login"),
    path("admin/", admin.site.urls),
    path("", include("web.urls")),
]