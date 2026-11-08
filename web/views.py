from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def home(request):
    return redirect("overview" if request.user.is_authenticated else "signin")


@login_required
def overview(request):
        return render(request, "overview.html", {"active": "overview"})