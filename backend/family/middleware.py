"""HTTP caching rules for private responses.

Authenticated API responses (including ``/api/auth/me/``) carry the
requesting user's private data, and account pages carry CSRF tokens, yet
Django/DRF send no ``Cache-Control`` header for them by default. Without
an explicit ``no-store`` directive, browsers may keep those responses in
the HTTP cache or restore them from the back/forward cache — showing one
user's name and family data after logout, account switching, or
back-button navigation.

This middleware marks every ``/api/`` and ``/accounts/`` response as
non-storable. Static assets and other paths are untouched.
"""

API_PREFIXES = ("/api/", "/accounts/")


class NoStoreApiMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(API_PREFIXES):
            response["Cache-Control"] = "no-store, no-cache"
            response["Pragma"] = "no-cache"
        return response
