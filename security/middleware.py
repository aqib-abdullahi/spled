from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve

from .throttle import clear, client_ip, hit, limited

REDIRECTS = (301, 302, 303)


def _field(request, name):
    return (request.POST.get(name) or "").strip().lower()[:254]


def _blocked(request):
    response = render(request, "throttled.html", status=429)
    response["Retry-After"] = "900"
    return response


class AuthThrottleMiddleware:
    """Rate limits for sign-in, sign-up, resend and password reset."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.handlers = {
            "signin": self.signin,
            "signup": self.signup,
            "resend_verification": lambda r: self.email_flow(r, "signup_sent"),
            "password_reset": lambda r: self.email_flow(r, "password_reset_done"),
        }

    def __call__(self, request):
        if request.method == "POST":
            try:
                name = resolve(request.path_info).url_name
            except Resolver404:
                name = None
            handler = self.handlers.get(name)
            if handler:
                return handler(request)
        return self.get_response(request)

    def signin(self, request):
        ip = client_ip(request)
        pair = f"{ip}|{_field(request, 'username')}"
        if limited("signin_pair", pair) or limited("signin_ip", ip):
            return _blocked(request)
        response = self.get_response(request)
        if response.status_code == 200:  # the form came back: sign-in failed
            hit("signin_pair", pair)
            hit("signin_ip", ip)
        elif response.status_code in REDIRECTS:
            clear("signin_pair", pair)
        return response

    def signup(self, request):
        ip = client_ip(request)
        email = _field(request, "email")
        if limited("signup_ip", ip):
            return _blocked(request)
        if email and limited("email_target", email):
            return redirect("signup_sent")  # looks like success; nothing is sent
        response = self.get_response(request)
        if response.status_code in REDIRECTS:  # only completed requests count
            hit("signup_ip", ip)
            if email:
                hit("email_target", email)
        return response

    def email_flow(self, request, done_url_name):
        ip = client_ip(request)
        email = _field(request, "email")
        if limited("email_ip", ip) or (email and limited("email_target", email)):
            return redirect(done_url_name)  # looks like success; nothing is sent
        response = self.get_response(request)
        if response.status_code in REDIRECTS:
            hit("email_ip", ip)
            if email:
                hit("email_target", email)
        return response


class SecurityHeadersMiddleware:
    PERMISSIONS = "geolocation=(self), camera=(), microphone=(), payment=(), usb=()"
    CSP = "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", self.PERMISSIONS)
        response.headers.setdefault("Content-Security-Policy", self.CSP)
        return response