from django.http import JsonResponse


def health(request):
    """Minimal liveness endpoint.

    Returns a small JSON payload and deliberately exposes no configuration,
    database details, or secrets. It performs no database queries so it keeps
    working before MySQL is configured.
    """
    return JsonResponse(
        {
            "status": "ok",
            "service": "mycelium-backend",
            "version": "0.1.0",
        }
    )
