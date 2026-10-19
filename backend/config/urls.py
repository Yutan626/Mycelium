from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse

# Simple view to show a message on the homepage
def home_api_root(request):
    return JsonResponse({"message": "Welcome to the Mycelium API Backend!"})

urlpatterns = [
    path('', home_api_root),  # This fixes the 404 homepage error
    path('admin/', admin.site.urls),
    path('api/', include('family.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
]
