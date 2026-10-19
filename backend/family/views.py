import mimetypes

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models import Q
from django.http import FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from groq import APITimeoutError as GroqTimeoutError
from groq import Groq
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .gazetteer import resolve_place
from .models import FamilyEvent, FamilyMember, FamilyStory, FamilyTree, RelativeConnection
from .permissions import IsConnectionParty, IsOwner, can_view_tree
from .serializers import (
    FamilyEventSerializer,
    FamilyMemberSerializer,
    FamilyStorySerializer,
    LoginSerializer,
    RegisterSerializer,
    RelativeConnectionSerializer,
    StoryHelperSerializer,
)


def health(request):
    """Minimal liveness endpoint.

    Returns a small JSON payload and deliberately exposes no configuration,
    database details, or secrets. It performs no database queries so it keeps
    working even when no production database is configured.
    """
    return JsonResponse(
        {
            "status": "ok",
            "service": "mycelium-backend",
            "version": "0.1.0",
        }
    )


class OwnerScopedMixin:
    """Limit list/detail querysets to the requesting user's own records and
    stamp new records with the request user (never a client-supplied owner)."""

    def get_queryset(self):
        return super().get_queryset().filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


# ---------------- Authentication (session based, no extra dependencies) ----


class RegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        return Response(
            {"id": user.pk, "username": user.username, "email": user.email},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    # Brute-force protection without extra dependencies (backed by Django's
    # cache; swap in django-axes/Redis if lockouts must survive restarts or
    # span multiple processes).
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_BLOCK_SECONDS = 300

    def throttle_key(self, request):
        ip = request.META.get("REMOTE_ADDR", "unknown")
        return f"login-attempts:{ip}"

    def post(self, request):
        key = self.throttle_key(request)
        if (cache.get(key) or 0) >= self.MAX_LOGIN_ATTEMPTS:
            return Response(
                {"detail": "Too many login attempts. Try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        serializer = LoginSerializer(data=request.data, context={"request": request})
        if not serializer.is_valid():
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, self.LOGIN_BLOCK_SECONDS)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        cache.delete(key)
        user = serializer.validated_data["user"]
        login(request, user)
        return Response({"id": user.pk, "username": user.username, "email": user.email})


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


class MeView(APIView):
    def get(self, request):
        user = request.user
        tree, _ = FamilyTree.objects.get_or_create(owner=user)
        center = tree.center_member
        return Response(
            {
                "id": user.pk,
                "username": user.username,
                "email": user.email,
                "centerMemberId": center.pk if center is not None else None,
            }
        )


class CsrfView(APIView):
    """Set the CSRF cookie for browser clients (no session required)."""

    permission_classes = [permissions.AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({"detail": "CSRF cookie set."})


# ---------------- Family records (all owner-scoped) ------------------------


class MemberListCreateView(OwnerScopedMixin, generics.ListCreateAPIView):
    """GET /api/members/ (tree + profiles) and POST /api/members/ (forms).

    Accepts both JSON and multipart form payloads — the frontend submits its
    member forms as ``FormData`` (including the optional ``photo`` file).
    Only the requesting user's own members are ever listed or created.
    """

    queryset = FamilyMember.objects.all().prefetch_related("parents", "partners")
    serializer_class = FamilyMemberSerializer


class MemberDetailView(OwnerScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    queryset = FamilyMember.objects.all().prefetch_related("parents", "partners")
    serializer_class = FamilyMemberSerializer


class EventListCreateView(OwnerScopedMixin, generics.ListCreateAPIView):
    """GET /api/events/ (timeline) and POST /api/events/."""

    queryset = FamilyEvent.objects.all().select_related("member")
    serializer_class = FamilyEventSerializer


class EventDetailView(OwnerScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    queryset = FamilyEvent.objects.all().select_related("member")
    serializer_class = FamilyEventSerializer


class StoryListCreateView(OwnerScopedMixin, generics.ListCreateAPIView):
    """GET /api/stories/ (story archive) and POST /api/stories/."""

    queryset = FamilyStory.objects.all().select_related("member")
    serializer_class = FamilyStorySerializer


class StoryDetailView(OwnerScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    queryset = FamilyStory.objects.all().select_related("member")
    serializer_class = FamilyStorySerializer


class MemberPhotoView(APIView):
    """GET /api/photos/<member id>/ — checked photo download.

    Served through the backend (never a public media URL) so access stays
    enforceable on any storage backend, local or Cloudinary. The owning
    account, or an explicitly granted viewer, gets the file; anyone else
    gets 404 and anonymous users get 403.
    """

    def get(self, request, pk):
        member = get_object_or_404(FamilyMember, pk=pk)
        if (
            member.owner is None
            or request.user.is_anonymous
            or not can_view_tree(request.user, member.owner)
        ):
            raise Http404
        if not member.photo:
            return Response(
                {"detail": "This member has no photo."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            member.photo.open("rb")
        except (FileNotFoundError, OSError, ValueError):
            return Response(
                {"detail": "The photo file is unavailable."},
                status=status.HTTP_404_NOT_FOUND,
            )
        content_type, _ = mimetypes.guess_type(member.photo.name)
        return FileResponse(
            member.photo, content_type=content_type or "application/octet-stream"
        )


class CenterView(APIView):
    """GET/POST /api/center/ — the person at the center of the user's tree.

    POST takes ``{"memberId": <own member id>}`` and is idempotent. Only the
    requesting user's own members are accepted; anything else is a generic
    404 that reveals nothing about other accounts.
    """

    def get_tree(self, request):
        tree, _ = FamilyTree.objects.get_or_create(owner=request.user)
        return tree

    def serialize_center(self, tree, request):
        member = tree.center_member
        if member is None:
            return Response({"member": None})
        data = FamilyMemberSerializer(member, context={"request": request}).data
        return Response({"member": data})

    def get(self, request):
        return self.serialize_center(self.get_tree(request), request)

    def post(self, request):
        member_id = request.data.get("memberId")
        if not member_id:
            return Response(
                {"memberId": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        member = get_object_or_404(FamilyMember, pk=member_id, owner=request.user)
        tree = self.get_tree(request)
        tree.center_member = member
        tree.save(update_fields=["center_member"])
        return self.serialize_center(tree, request)


class PlaceListView(APIView):
    """GET /api/places/ — globe points derived from member places.

    Each member contributes up to two entries: one for ``birthPlace``
    (``kind: "birth"``) and one for ``livedPlace`` (``kind: "lived"``).
    Coordinates come from the local gazetteer and stay ``null`` for
    unrecognized places; the keys are always present so the frontend
    contract stays stable. Only places belonging to the requesting user's
    own members are included.
    """

    def get(self, request):
        places = []
        members = FamilyMember.objects.filter(owner=request.user).order_by(
            "name", "id"
        )
        for member in members:
            for place_text, kind in (
                (member.birth_place, "birth"),
                (member.lived_place, "lived"),
            ):
                if not place_text:
                    continue
                lat, lng = resolve_place(place_text)
                places.append(
                    {
                        "name": member.name,
                        "place": place_text,
                        "lat": lat,
                        "lng": lng,
                        "kind": kind,
                    }
                )
        return Response(places)


class StoryHelperThrottle(UserRateThrottle):
    """Per-account rate limit for AI generation (abuse + cost control)."""

    scope = "storyhelper"

    def get_rate(self):
        # Read live from settings: DRF binds THROTTLE_RATES on the base
        # class at import time, which would otherwise freeze the very first
        # settings seen (breaking settings overrides in tests).
        from rest_framework.settings import api_settings

        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)


class StoryHelperView(APIView):
    """POST /api/storyhelper/ — AI-assisted story improvement via Groq.

    The Groq API key is read from the ``GROQ_API_KEY`` environment variable
    (backend only) and is never included in responses, logs, or frontend
    code. When no key is configured the endpoint answers 503 instead of
    pretending to help. Only the user's own submitted text is sent to the
    provider — never another account's records.
    """

    throttle_classes = [StoryHelperThrottle]

    def post(self, request):
        serializer = StoryHelperSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        api_key = settings.GROQ_API_KEY
        if not api_key:
            return Response(
                {
                    "detail": "Story helper is not configured on the server "
                    "(missing GROQ_API_KEY)."
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        text = serializer.validated_data["text"]
        title = serializer.validated_data.get("title", "")
        prompt = (
            "Improve the following family story for clarity, warmth and "
            "readability. Preserve all facts, names, dates and places. "
            "Return only the improved story text, without commentary."
        )
        if title:
            prompt += f'\n\nStory title: "{title}"'
        prompt += f"\n\nStory:\n{text}"

        try:
            client = Groq(api_key=api_key)
            completion = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a thoughtful editor helping a "
                        "family preserve its stories.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1024,
                timeout=30,
            )
            improved = completion.choices[0].message.content
        except GroqTimeoutError:
            return Response(
                {
                    "detail": "The story helper timed out. Please try again later."
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except Exception:
            return Response(
                {"detail": "Story helper request failed. Please try again later."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"improved_text": improved, "model": settings.GROQ_MODEL})


class ConnectionListCreateView(generics.ListCreateAPIView):
    """GET/POST /api/connections/ — relative links between accounts.

    Minimal, private-by-default foundation: users are addressed by exact
    username (there is no user directory), records are never merged, and an
    approved link grants no viewing or editing rights — it only records
    that the two accounts consider themselves related.
    """

    serializer_class = RelativeConnectionSerializer

    def get_queryset(self):
        user = self.request.user
        return (
            RelativeConnection.objects.filter(Q(from_user=user) | Q(to_user=user))
            .select_related("from_user", "to_user", "from_member")
            .order_by("-updated_at", "-id")
        )


class ConnectionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/connections/<id>/.

    PATCH accepts ``{"status": "approved"|"rejected"}`` from the recipient
    while the request is pending, and ``{"grants_view": true|false}`` from
    the recipient once approved (granting read-only tree viewing, which the
    recipient can revoke the same way). DELETE by either party removes the
    thread (revoke) without touching any family records.
    """

    permission_classes = [permissions.IsAuthenticated, IsConnectionParty]
    serializer_class = RelativeConnectionSerializer

    def get_queryset(self):
        user = self.request.user
        return RelativeConnection.objects.filter(
            Q(from_user=user) | Q(to_user=user)
        ).select_related("from_user", "to_user", "from_member")

    def update(self, request, *args, **kwargs):
        connection = self.get_object()
        if request.user != connection.to_user:
            return Response(
                {"detail": "Only the recipient can answer this request."},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data
        if "status" not in data and "grants_view" not in data:
            return Response(
                {"detail": "Provide 'status' and/or 'grants_view'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if "status" in data:
            if connection.status != RelativeConnection.STATUS_PENDING:
                return Response(
                    {"detail": "This request has already been answered."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            new_status = data.get("status")
            if new_status not in (
                RelativeConnection.STATUS_APPROVED,
                RelativeConnection.STATUS_REJECTED,
            ):
                return Response(
                    {"status": ["Choose 'approved' or 'rejected'."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            connection.status = new_status
        if "grants_view" in data:
            if connection.status != RelativeConnection.STATUS_APPROVED:
                return Response(
                    {
                        "detail": "Viewing access can only be granted on "
                        "approved connections."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            grants_view = data.get("grants_view")
            if grants_view not in (True, False):
                return Response(
                    {"grants_view": ["Must be true or false."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            connection.grants_view = grants_view
        connection.save(update_fields=["status", "grants_view", "updated_at"])
        serializer = self.get_serializer(connection)
        return Response(serializer.data)


def resolve_shared_owner(request, username):
    """Account whose tree ``request.user`` wants to view, if permitted."""
    try:
        target = User.objects.get(username=username)
    except User.DoesNotExist:
        raise Http404
    if not can_view_tree(request.user, target):
        raise Http404
    return target


class SharedMemberListView(generics.ListAPIView):
    """GET /api/shared/<username>/members/ — read-only shared tree viewing."""

    serializer_class = FamilyMemberSerializer

    def get_queryset(self):
        target = resolve_shared_owner(self.request, self.kwargs["username"])
        return FamilyMember.objects.filter(owner=target).prefetch_related(
            "parents", "partners"
        )


class SharedEventListView(generics.ListAPIView):
    """GET /api/shared/<username>/events/ — read-only shared timeline."""

    serializer_class = FamilyEventSerializer

    def get_queryset(self):
        target = resolve_shared_owner(self.request, self.kwargs["username"])
        return FamilyEvent.objects.filter(owner=target).select_related("member")


class SharedStoryListView(generics.ListAPIView):
    """GET /api/shared/<username>/stories/ — read-only shared archive."""

    serializer_class = FamilyStorySerializer

    def get_queryset(self):
        target = resolve_shared_owner(self.request, self.kwargs["username"])
        return FamilyStory.objects.filter(owner=target).select_related("member")


class SharedPlaceListView(APIView):
    """GET /api/shared/<username>/places/ — read-only shared locations."""

    def get(self, request, username):
        target = resolve_shared_owner(request, username)
        places = []
        members = FamilyMember.objects.filter(owner=target).order_by("name", "id")
        for member in members:
            for place_text, kind in (
                (member.birth_place, "birth"),
                (member.lived_place, "lived"),
            ):
                if not place_text:
                    continue
                lat, lng = resolve_place(place_text)
                places.append(
                    {
                        "name": member.name,
                        "place": place_text,
                        "lat": lat,
                        "lng": lng,
                        "kind": kind,
                    }
                )
        return Response(places)
