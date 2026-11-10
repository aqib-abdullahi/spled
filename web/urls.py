from django.contrib.auth import views as auth_views
from django.urls import path

from . import public_views, views

urlpatterns = [
    path("", public_views.public_home, name="home"),
    path("projects/", public_views.public_projects, name="projects"),
    path("projects/<int:pk>/", public_views.public_project, name="project"),
    path(
        "signin/",
        auth_views.LoginView.as_view(
            template_name="sign_in.html", redirect_authenticated_user=True
        ),
        name="signin",
    ),
    path("signout/", auth_views.LogoutView.as_view(), name="signout"),
    path("app/", views.overview, name="overview"),
    path("app/sites/", views.sites_list, name="sites"),
    path("app/sites/new/", views.site_create, name="site_new"),
    path("app/sites/<int:pk>/edit/", views.site_edit, name="site_edit"),
    path("app/sites/<int:pk>/", views.site_detail, name="site_detail"),
    path("app/sites/<int:pk>/evidence/new/", views.evidence_new, name="evidence_new"),
    path("app/sites/<int:pk>/publish/", views.site_publish, name="site_publish"),
    path("app/review/", views.review_queue, name="review"),
    path("app/review/<int:pk>/", views.review_decide, name="review_decide"),
]