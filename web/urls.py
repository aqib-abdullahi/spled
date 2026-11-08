from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path(
        "signin/",
        auth_views.LoginView.as_view(
            template_name="sign_in.html", redirect_authenticated_user=True
        ),
        name="signin",
    ),
    path("signout/", auth_views.LogoutView.as_view(), name="signout"),
    path("app/", views.overview, name="overview"),
]