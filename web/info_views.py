from django.conf import settings
from django.shortcuts import render

from registry.models import VERIFY_RADIUS_M


def _page(template, active):
    def view(request):
        return render(request, template, {
            "active": active,
            "contact_email": getattr(settings, "CONTACT_EMAIL", ""),
        })
    return view


def how_it_works(request):
    return render(request, "info_how.html", {
        "active": "how",
        "verify_radius": VERIFY_RADIUS_M,
    })


about = _page("info_about.html", "about")
contact = _page("info_contact.html", "contact")
privacy = _page("info_privacy.html", "privacy")
terms = _page("info_terms.html", "terms")