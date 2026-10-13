from django.conf import settings
from django.http import JsonResponse
from groq import Groq
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FamilyEvent, FamilyMember, FamilyStory
from .serializers import (
    FamilyEventSerializer,
    FamilyMemberSerializer,
    FamilyStorySerializer,
    StoryHelperSerializer,
)


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


class MemberListCreateView(generics.ListCreateAPIView):
    """GET /api/members/ (tree + profiles) and POST /api/members/ (forms).

    Accepts both JSON and multipart form payloads — the frontend submits its
    member forms as ``FormData`` (including the optional ``photo`` file).
    """

    queryset = FamilyMember.objects.all().prefetch_related("parents", "partners")
    serializer_class = FamilyMemberSerializer


class MemberDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FamilyMember.objects.all().prefetch_related("parents", "partners")
    serializer_class = FamilyMemberSerializer


class EventListCreateView(generics.ListCreateAPIView):
    """GET /api/events/ (timeline) and POST /api/events/."""

    queryset = FamilyEvent.objects.all().select_related("member")
    serializer_class = FamilyEventSerializer


class EventDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FamilyEvent.objects.all().select_related("member")
    serializer_class = FamilyEventSerializer


class StoryListCreateView(generics.ListCreateAPIView):
    """GET /api/stories/ (story archive) and POST /api/stories/."""

    queryset = FamilyStory.objects.all().select_related("member")
    serializer_class = FamilyStorySerializer


class StoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = FamilyStory.objects.all().select_related("member")
    serializer_class = FamilyStorySerializer


class PlaceListView(APIView):
    """GET /api/places/ — globe points derived from member places.

    Each member contributes up to two entries: one for ``birthPlace``
    (``kind: "birth"``) and one for ``livedPlace`` (``kind: "lived"``).
    ``lat``/``lng`` are ``null`` until geocoding is implemented; the keys
    are present so the frontend contract stays stable.
    """

    def get(self, request):
        places = []
        for member in FamilyMember.objects.all().order_by("name", "id"):
            if member.birth_place:
                places.append(
                    {
                        "name": member.name,
                        "place": member.birth_place,
                        "lat": None,
                        "lng": None,
                        "kind": "birth",
                    }
                )
            if member.lived_place:
                places.append(
                    {
                        "name": member.name,
                        "place": member.lived_place,
                        "lat": None,
                        "lng": None,
                        "kind": "lived",
                    }
                )
        return Response(places)


class StoryHelperView(APIView):
    """POST /api/storyhelper/ — AI-assisted story improvement via Groq.

    The Groq API key is read from the ``GROQ_API_KEY`` environment variable
    (backend only) and is never included in responses, logs, or frontend
    code. When no key is configured the endpoint answers 503 instead of
    pretending to help.
    """

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
            )
            improved = completion.choices[0].message.content
        except Exception:
            return Response(
                {"detail": "Story helper request failed. Please try again later."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"improved_text": improved, "model": settings.GROQ_MODEL})
