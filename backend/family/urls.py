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
    re_path(r"^auth/register/?$", views.RegisterView.as_view(), name="register"),
    re_path(r"^auth/login/?$", views.LoginView.as_view(), name="login"),
    re_path(r"^auth/logout/?$", views.LogoutView.as_view(), name="logout"),
    re_path(r"^auth/me/?$", views.MeView.as_view(), name="me"),
    re_path(r"^auth/csrf/?$", views.CsrfView.as_view(), name="csrf"),
    re_path(r"^center/?$", views.CenterView.as_view(), name="center"),
    re_path(
        r"^photos/(?P<pk>\d+)/?$",
        views.MemberPhotoView.as_view(),
        name="member-photo",
    ),
    re_path(
        r"^connections/?$",
        views.ConnectionListCreateView.as_view(),
        name="connection-list",
    ),
    re_path(
        r"^connections/(?P<pk>\d+)/?$",
        views.ConnectionDetailView.as_view(),
        name="connection-detail",
    ),
    re_path(
        r"^shared/(?P<username>[\w.@+-]+)/members/?$",
        views.SharedMemberListView.as_view(),
        name="shared-member-list",
    ),
    re_path(
        r"^shared/(?P<username>[\w.@+-]+)/events/?$",
        views.SharedEventListView.as_view(),
        name="shared-event-list",
    ),
    re_path(
        r"^shared/(?P<username>[\w.@+-]+)/stories/?$",
        views.SharedStoryListView.as_view(),
        name="shared-story-list",
    ),
    re_path(
        r"^shared/(?P<username>[\w.@+-]+)/places/?$",
        views.SharedPlaceListView.as_view(),
        name="shared-place-list",
    ),
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
