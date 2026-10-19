from django.contrib import admin
from django.urls import include, path
from django.shortcuts import render
from django.conf import settings
from django.conf.urls.static import static

# This function tells Django to load your index.html file
def homepage_view(request):
    return render(request, 'index.html')

urlpatterns = [
    path('', homepage_view),  # This forces your website to load on the main URL
    path('admin/', admin.site.urls),
    path('api/', include('family.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
]

# This tells Django where to look for your script.js and style.css files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
