from django.http import HttpResponse
import re

allowed_headers = (
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
)

allowed_methods = (
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
)

class CorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if response := self.preflight(request):
            self.add_response_headers(request, response)
            return response
        else:
            response = self.get_response(request)
            self.add_response_headers(request, response)
            return response

    def preflight(self, request):
        request._cors_enabled = self.is_enabled(request)
        if request._cors_enabled and request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            return HttpResponse(headers={"content-length": "0"})
        else:
            return None

    def add_response_headers(self, request, response):
        enabled = getattr(request, "_cors_enabled", None)
        if enabled is None:
            enabled = self.is_enabled(request)

        if not enabled:
            return response

        response["Access-Control-Allow-Origin"] = "*"

        if request.method == "OPTIONS":
            response["Access-Control-Allow-Headers"] = ", ".join(allowed_headers)
            response["Access-Control-Allow-Methods"] = ", ".join(allowed_methods)

        return response

    @staticmethod
    def is_enabled(request):
        if request.path_info.startswith("/api/v1/device"):
            return True
        elif re.fullmatch(r"^/api/v1/organizers/([^/]+)/uic_keys/$", request.path_info):
            return True
        elif re.fullmatch(r"^/api/v1/organizers/([^/]+)/wallets/.*$", request.path_info):
            return True
        else:
            return False