"""URL routes for the family app.

Only the health endpoint is implemented in this foundation task. The remaining
application endpoints (members, places, events, stories, storyhelper) are
planned and will be added in a later, separately verified step.
"""

from django.urls import path

from . import views

app_name = "family"

urlpatterns = [
    path("health/", views.health, name="health"),
]
