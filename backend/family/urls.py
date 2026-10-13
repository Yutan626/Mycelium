"""URL routes for the family app.

Trailing slashes are optional on every route: the frontend calls
``/api/members`` without a slash, and a redirect on POST would drop the
request body, so both spellings are served directly.
"""

from django.urls import re_path

from . import views

app_name = "family"

urlpatterns = [
    re_path(r"^health/?$", views.health, name="health"),
    re_path(r"^members/?$", views.MemberListCreateView.as_view(), name="member-list"),
    re_path(
        r"^members/(?P<pk>\d+)/?$",
        views.MemberDetailView.as_view(),
        name="member-detail",
    ),
    re_path(r"^events/?$", views.EventListCreateView.as_view(), name="event-list"),
    re_path(
        r"^events/(?P<pk>\d+)/?$",
        views.EventDetailView.as_view(),
        name="event-detail",
    ),
    re_path(r"^stories/?$", views.StoryListCreateView.as_view(), name="story-list"),
    re_path(
        r"^stories/(?P<pk>\d+)/?$",
        views.StoryDetailView.as_view(),
        name="story-detail",
    ),
    re_path(r"^places/?$", views.PlaceListView.as_view(), name="place-list"),
    re_path(r"^storyhelper/?$", views.StoryHelperView.as_view(), name="story-helper"),
]
