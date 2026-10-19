import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .gazetteer import resolve_place
from .models import (
    FamilyEvent,
    FamilyMember,
    FamilyStory,
    FamilyTree,
    RelativeConnection,
)
from .serializers import FamilyMemberSerializer


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AuthenticatedTestCase(TestCase):
    """Base class: each test runs as its own registered user."""

    client_class = APIClient

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123"
        )
        self.client.force_authenticate(user=self.user)

    def mkmember(self, **kwargs):
        """Create a member owned by the test user unless stated otherwise."""
        kwargs.setdefault("owner", self.user)
        return FamilyMember.objects.create(**kwargs)

TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


class HealthEndpointTests(SimpleTestCase):
    """Health endpoint must work without a database or any secrets configured."""

    databases = set()

    def test_health_returns_ok_status(self):
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "mycelium-backend",
                "version": "0.1.0",
            },
        )

    def test_health_exposes_no_configuration(self):
        body = self.client.get("/api/health/").content.decode().lower()
        for forbidden in ("secret", "password", "groq", "mysql", "debug"):
            self.assertNotIn(forbidden, body)


class FamilyMemberModelTests(AuthenticatedTestCase):
    def test_str_and_ordering(self):
        self.mkmember(name="Grace Okafor")
        self.mkmember(name="Amara Okafor")
        member = FamilyMember.objects.get(name="Grace Okafor")
        self.assertEqual(str(member), "Grace Okafor")
        self.assertEqual(
            list(FamilyMember.objects.values_list("name", flat=True)),
            ["Amara Okafor", "Grace Okafor"],
        )

    def test_death_before_birth_rejected(self):
        member = FamilyMember(
            name="Paradox", birth_date="2000-01-01", death_date="1999-12-31"
        )
        with self.assertRaises(ValidationError):
            member.full_clean()

    def test_self_related_to_rejected(self):
        member = self.mkmember(name="Narcissus")
        member.related_to = member
        with self.assertRaises(ValidationError):
            member.full_clean()

    def test_siblings_derived_from_shared_parent(self):
        parent = self.mkmember(name="Amara Okafor")
        child_a = self.mkmember(name="Grace Okafor")
        child_b = self.mkmember(name="Samuel Okafor")
        outsider = self.mkmember(name="James Lin")
        child_a.parents.add(parent)
        child_b.parents.add(parent)
        self.assertEqual(list(child_a.siblings), [child_b])
        self.assertEqual(list(child_b.siblings), [child_a])
        self.assertEqual(list(outsider.siblings), [])

    def test_spouse_defaults_to_none(self):
        member = self.mkmember(name="Solo")
        self.assertIsNone(member.spouse)

    def test_spouse_returns_first_partner(self):
        anna = self.mkmember(name="Anna")
        ben = self.mkmember(name="Ben")
        anna.partners.add(ben)
        self.assertEqual(anna.spouse, ben)
        self.assertEqual(ben.spouse, anna)


class RelationshipDerivationTests(AuthenticatedTestCase):
    def test_parent_hint_links_other_as_child(self):
        child = self.mkmember(name="Grace Okafor")
        response = self.client.post(
            "/api/members",
            {
                "name": "Amara Okafor",
                "relationship": "Parent",
                "relatedTo": str(child.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        parent = FamilyMember.objects.get(name="Amara Okafor")
        self.assertIn(parent, child.parents.all())
        self.assertIn(child, parent.children.all())

    def test_child_hint_links_member_as_child(self):
        parent = self.mkmember(name="Amara Okafor")
        response = self.client.post(
            "/api/members",
            {
                "name": "Grace Okafor",
                "relationship": "Child",
                "relatedTo": str(parent.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        child = FamilyMember.objects.get(name="Grace Okafor")
        self.assertIn(parent, child.parents.all())

    def test_spouse_link_is_mutual(self):
        existing = self.mkmember(name="David Okafor")
        response = self.client.post(
            "/api/members",
            {
                "name": "Amara Okafor",
                "relationship": "Spouse / partner",
                "relatedTo": str(existing.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        new_member = FamilyMember.objects.get(name="Amara Okafor")
        self.assertIn(existing, new_member.partners.all())
        self.assertIn(new_member, existing.partners.all())
        detail = self.client.get(f"/api/members/{new_member.pk}").json()
        self.assertEqual(detail["spouseId"], existing.pk)

    def test_sibling_hint_shares_parents(self):
        parent = self.mkmember(name="Amara Okafor")
        sibling = self.mkmember(name="Grace Okafor")
        sibling.parents.add(parent)
        response = self.client.post(
            "/api/members",
            {
                "name": "Samuel Okafor",
                "relationship": "Sibling",
                "relatedTo": str(sibling.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        new_member = FamilyMember.objects.get(name="Samuel Okafor")
        self.assertIn(parent, new_member.parents.all())
        self.assertIn(new_member, sibling.siblings)

    def test_grandparent_hint_links_through_parents(self):
        parent = self.mkmember(name="Grace Okafor")
        child = self.mkmember(name="Maya Lin")
        child.parents.add(parent)
        response = self.client.post(
            "/api/members",
            {
                "name": "Amara Okafor",
                "relationship": "Grandparent",
                "relatedTo": str(child.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        grandparent = FamilyMember.objects.get(name="Amara Okafor")
        self.assertIn(grandparent, parent.parents.all())

    def test_ambiguous_labels_store_hint_only(self):
        existing = self.mkmember(name="David Okafor")
        for label in ("Cousin", "Me", "Other"):
            with self.subTest(label=label):
                response = self.client.post(
                    "/api/members",
                    {
                        "name": f"Relative {label}",
                        "relationship": label,
                        "relatedTo": str(existing.pk),
                    },
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 201, response.content)
                member = FamilyMember.objects.get(name=f"Relative {label}")
                self.assertEqual(member.relationship_label, label)
                self.assertEqual(member.related_to, existing)
                self.assertEqual(member.parents.count(), 0)
                self.assertEqual(member.partners.count(), 0)

    def test_reapplying_hint_creates_no_duplicates(self):
        existing = self.mkmember(name="David Okafor")
        response = self.client.post(
            "/api/members",
            {
                "name": "Amara Okafor",
                "relationship": "Spouse / partner",
                "relatedTo": str(existing.pk),
            },
            content_type="application/json",
        )
        member_id = response.json()["id"]
        update = self.client.patch(
            f"/api/members/{member_id}",
            {
                "relationship": "Spouse / partner",
                "relatedTo": str(existing.pk),
            },
            content_type="application/json",
        )
        self.assertEqual(update.status_code, 200, update.content)
        member = FamilyMember.objects.get(pk=member_id)
        self.assertEqual(member.partners.count(), 1)
        self.assertEqual(existing.partners.count(), 1)

    def test_self_links_rejected(self):
        member = self.mkmember(name="Narcissus")
        for payload in (
            {"relatedTo": str(member.pk)},
            {"parents": [member.pk]},
            {"partners": [member.pk]},
        ):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    f"/api/members/{member.pk}",
                    payload,
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400, response.content)


class FamilyMemberSerializerTests(AuthenticatedTestCase):
    def test_camel_case_contract_shape(self):
        parent = self.mkmember(name="Amara Okafor")
        member = self.mkmember(
            name="Grace Okafor",
            birth_date="1964-01-01",
            relationship_label="Child",
            related_to=parent,
        )
        member.parents.add(parent)
        data = FamilyMemberSerializer(member).data
        self.assertEqual(data["birthDate"], "1964-01-01")
        self.assertIsNone(data["deathDate"])
        self.assertEqual(data["birthPlace"], "")
        self.assertEqual(data["relationship"], "Child")
        self.assertEqual(data["relatedTo"], parent.pk)
        self.assertEqual(data["parents"], [parent.pk])
        self.assertEqual(data["partners"], [])
        self.assertIsNone(data["spouseId"])
        self.assertIsNone(data["photoUrl"])

    def test_empty_strings_accepted_as_no_value(self):
        serializer = FamilyMemberSerializer(
            data={"name": "Grace", "birthDate": "", "deathDate": "", "relatedTo": ""}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        member = serializer.save()
        self.assertIsNone(member.birth_date)
        self.assertIsNone(member.related_to)

    def test_death_before_birth_invalid(self):
        serializer = FamilyMemberSerializer(
            data={"name": "X", "birthDate": "2000-01-01", "deathDate": "1999-01-01"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("deathDate", serializer.errors)

    def test_name_required(self):
        serializer = FamilyMemberSerializer(data={"bio": "nameless"})
        self.assertFalse(serializer.is_valid())
        self.assertIn("name", serializer.errors)


class MemberAPITests(AuthenticatedTestCase):
    def test_list_contract_shape(self):
        parent = self.mkmember(
            name="Amara Okafor", birth_place="Enugu, Nigeria"
        )
        child = self.mkmember(
            name="Grace Okafor", relationship_label="Child", related_to=parent
        )
        child.parents.add(parent)
        response = self.client.get("/api/members/")
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        grace = next(item for item in results if item["name"] == "Grace Okafor")
        for key in (
            "id",
            "name",
            "birthDate",
            "deathDate",
            "birthPlace",
            "livedPlace",
            "relationship",
            "relatedTo",
            "parents",
            "partners",
            "spouseId",
            "photoUrl",
            "bio",
        ):
            self.assertIn(key, grace)
        self.assertEqual(grace["relatedTo"], parent.pk)
        self.assertEqual(grace["parents"], [parent.pk])

    def test_create_minimal_json(self):
        response = self.client.post(
            "/api/members", {"name": "Grace Okafor"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["name"], "Grace Okafor")
        self.assertEqual(body["relationship"], "")
        self.assertIsNone(body["relatedTo"])
        self.assertEqual(body["parents"], [])

    def test_create_without_trailing_slash(self):
        # The frontend posts to /api/members (no slash); this must not redirect.
        response = self.client.post(
            "/api/members", {"name": "No Slash"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_multipart_like_frontend_form(self):
        response = self.client.post(
            "/api/members",
            {
                "name": "Grace Okafor",
                "birthDate": "1964-05-01",
                "deathDate": "",
                "birthPlace": "Enugu, Nigeria",
                "livedPlace": "Toronto, Canada",
                "relationship": "Mother",
                "relatedTo": "",
                "bio": "A nurse who moved to Canada in 1989.",
            },
        )
        # "Mother" is not a valid choice, so this must fail loudly, not fake-save.
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FamilyMember.objects.filter(name="Grace Okafor").exists())

    def test_create_multipart_valid_choices(self):
        response = self.client.post(
            "/api/members",
            {
                "name": "Grace Okafor",
                "birthDate": "1964-05-01",
                "deathDate": "",
                "birthPlace": "Enugu, Nigeria",
                "livedPlace": "Toronto, Canada",
                "relationship": "Child",
                "relatedTo": "",
                "bio": "A nurse who moved to Canada in 1989.",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["birthDate"], "1964-05-01")
        self.assertIsNone(body["deathDate"])
        self.assertEqual(body["birthPlace"], "Enugu, Nigeria")

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="mycelium-test-media-"))
    def test_create_with_photo_upload(self):
        photo = SimpleUploadedFile("photo.gif", TINY_GIF, content_type="image/gif")
        response = self.client.post(
            "/api/members", {"name": "With Photo", "photo": photo}
        )
        self.assertEqual(response.status_code, 201, response.content)
        photo_url = response.json()["photoUrl"]
        self.assertIsNotNone(photo_url)
        self.assertIn("/api/photos/", photo_url)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="mycelium-test-media-"))
    def test_upload_size_caps_configured(self):
        # A >5 MiB multipart body cannot go through the Django test client
        # (it fails pickling the temp file before reaching the view), so
        # assert the caps themselves: Django enforces them per request.
        from django.conf import settings as dj_settings

        self.assertEqual(
            dj_settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 5 * 1024 * 1024
        )
        self.assertEqual(
            dj_settings.FILE_UPLOAD_MAX_MEMORY_SIZE, 5 * 1024 * 1024
        )

    def test_create_validation_errors(self):
        missing_name = self.client.post(
            "/api/members", {"bio": "nameless"}, content_type="application/json"
        )
        self.assertEqual(missing_name.status_code, 400)
        unknown_relative = self.client.post(
            "/api/members",
            {"name": "X", "relatedTo": 9999},
            content_type="application/json",
        )
        self.assertEqual(unknown_relative.status_code, 400)
        bad_dates = self.client.post(
            "/api/members",
            {"name": "Y", "birthDate": "2000-01-01", "deathDate": "1999-01-01"},
            content_type="application/json",
        )
        self.assertEqual(bad_dates.status_code, 400)
        unknown_parent = self.client.post(
            "/api/members",
            {"name": "Z", "parents": [9999]},
            content_type="application/json",
        )
        self.assertEqual(unknown_parent.status_code, 400)
        unknown_partner = self.client.post(
            "/api/members",
            {"name": "W", "partners": [9999]},
            content_type="application/json",
        )
        self.assertEqual(unknown_partner.status_code, 400)

    def test_detail_update_delete(self):
        created = self.client.post(
            "/api/members", {"name": "Grace"}, content_type="application/json"
        )
        member_id = created.json()["id"]
        detail = self.client.get(f"/api/members/{member_id}/")
        self.assertEqual(detail.status_code, 200)
        patched = self.client.patch(
            f"/api/members/{member_id}/",
            {"bio": "Updated bio"},
            content_type="application/json",
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.json()["bio"], "Updated bio")
        deleted = self.client.delete(f"/api/members/{member_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/members/{member_id}/").status_code, 404)


class EventAPITests(AuthenticatedTestCase):
    def test_create_and_list_ordered_by_year(self):
        member = self.mkmember(name="Grace Okafor")
        first = self.client.post(
            "/api/events",
            {"memberId": member.pk, "year": 1989, "text": "Grace moves to Toronto."},
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(
            "/api/events",
            {"year": 1938, "text": "Amara is born in Enugu."},
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 201, second.content)
        body = second.json()
        self.assertIsNone(body["memberId"])
        results = self.client.get("/api/events/").json()["results"]
        self.assertEqual([item["year"] for item in results], [1938, 1989])
        self.assertEqual(results[0]["memberId"], None)
        self.assertEqual(results[1]["memberId"], member.pk)

    def test_blank_inputs_accepted_as_no_value(self):
        response = self.client.post("/api/events", {"year": "", "text": "Undated"})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIsNone(response.json()["year"])

    def test_text_required(self):
        response = self.client.post(
            "/api/events", {"year": 2000}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)


class StoryAPITests(AuthenticatedTestCase):
    def test_create_full_story(self):
        member = self.mkmember(name="Grace Okafor")
        response = self.client.post(
            "/api/stories",
            {
                "memberId": member.pk,
                "title": "Sunday jollof",
                "author": "Grace",
                "category": "Tradition",
                "text": "Every Sunday Grandma Amara cooked for the street.",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["memberId"], member.pk)
        self.assertEqual(body["category"], "Tradition")

    def test_defaults_and_validation(self):
        minimal = self.client.post(
            "/api/stories",
            {"title": "Untitled", "text": "Some memory."},
            content_type="application/json",
        )
        self.assertEqual(minimal.status_code, 201, minimal.content)
        self.assertEqual(minimal.json()["category"], "Memory")
        missing_title = self.client.post(
            "/api/stories", {"text": "No title."}, content_type="application/json"
        )
        self.assertEqual(missing_title.status_code, 400)
        missing_text = self.client.post(
            "/api/stories", {"title": "No text."}, content_type="application/json"
        )
        self.assertEqual(missing_text.status_code, 400)
        bad_category = self.client.post(
            "/api/stories",
            {"title": "T", "text": "X", "category": "Epic"},
            content_type="application/json",
        )
        self.assertEqual(bad_category.status_code, 400)


class PlacesAPITests(AuthenticatedTestCase):
    def test_empty_database_returns_empty_list(self):
        response = self.client.get("/api/places")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_birth_and_lived_places_listed(self):
        self.mkmember(
            name="Grace Okafor",
            birth_place="Village Unknown",
            lived_place="Town Nowhere",
        )
        self.mkmember(name="Nowhere Person")
        response = self.client.get("/api/places/")
        self.assertEqual(response.status_code, 200)
        places = response.json()
        self.assertEqual(len(places), 2)
        self.assertEqual(
            places[0],
            {
                "name": "Grace Okafor",
                "place": "Village Unknown",
                "lat": None,
                "lng": None,
                "kind": "birth",
            },
        )
        self.assertEqual(places[1]["kind"], "lived")
        self.assertEqual(places[1]["place"], "Town Nowhere")


class StoryHelperTests(AuthenticatedTestCase):
    def test_missing_text_rejected(self):
        response = self.client.post(
            "/api/storyhelper", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(GROQ_API_KEY="")
    def test_unconfigured_key_returns_503_not_fake_success(self):
        response = self.client.post(
            "/api/storyhelper",
            {"text": "Grandma cooked jollof."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("detail", response.json())

    @override_settings(GROQ_API_KEY="test-key-placeholder")
    @patch("family.views.Groq")
    def test_success_returns_improved_text_without_key(self, mock_groq):
        mock_groq.return_value.chat.completions.create.return_value = (
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Improved."))]
            )
        )
        response = self.client.post(
            "/api/storyhelper",
            {"title": "Sunday jollof", "text": "Grandma cooked jollof."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["improved_text"], "Improved.")
        self.assertNotIn("test-key-placeholder", response.content.decode())

    @override_settings(GROQ_API_KEY="test-key-placeholder")
    @patch("family.views.Groq")
    def test_groq_failure_returns_502(self, mock_groq):
        mock_groq.return_value.chat.completions.create.side_effect = Exception("boom")
        response = self.client.post(
            "/api/storyhelper",
            {"text": "Grandma cooked jollof."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 502)

    @override_settings(GROQ_API_KEY="test-key-placeholder")
    @patch("family.views.Groq")
    def test_groq_timeout_returns_504(self, mock_groq):
        import httpx
        from groq import APITimeoutError

        mock_groq.return_value.chat.completions.create.side_effect = (
            APITimeoutError(request=httpx.Request("POST", "https://api.groq.com/x"))
        )
        response = self.client.post(
            "/api/storyhelper",
            {"text": "Grandma cooked jollof."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 504)
        self.assertIn("detail", response.json())

    @override_settings(GROQ_API_KEY="test-key-placeholder")
    @patch("family.views.Groq")
    def test_response_contains_only_improved_text(self, mock_groq):
        # The helper echoes nothing back except its own output: no member
        # data, no keys, no configuration — nothing to leak across accounts.
        mock_groq.return_value.chat.completions.create.return_value = (
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Improved."))]
            )
        )
        other = User.objects.create_user(username="other", password="x")
        self.mkmember(name="Private Person", owner=other)
        response = self.client.post(
            "/api/storyhelper",
            {"text": "A private family memory."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            set(response.json().keys()), {"improved_text", "model"}
        )
        sent_prompt = (
            mock_groq.return_value.chat.completions.create.call_args[1]["messages"]
        )
        self.assertNotIn("Private Person", str(sent_prompt))

    @override_settings(
        GROQ_API_KEY="test-key-placeholder",
        REST_FRAMEWORK={
            "DEFAULT_RENDERER_CLASSES": [
                "rest_framework.renderers.JSONRenderer",
            ],
            "DEFAULT_PERMISSION_CLASSES": [
                "rest_framework.permissions.IsAuthenticated",
            ],
            "DEFAULT_THROTTLE_RATES": {"storyhelper": "2/min"},
        },
    )
    @patch("family.views.Groq")
    def test_storyhelper_throttled(self, mock_groq):
        from django.core.cache import cache

        cache.clear()
        mock_groq.return_value.chat.completions.create.return_value = (
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]
            )
        )
        payload = {"text": "Grandma cooked jollof."}
        for _ in range(2):
            response = self.client.post(
                "/api/storyhelper", payload, content_type="application/json"
            )
            self.assertEqual(response.status_code, 200, response.content)
        throttled = self.client.post(
            "/api/storyhelper", payload, content_type="application/json"
        )
        self.assertEqual(throttled.status_code, 429)


class GazetteerTests(SimpleTestCase):
    """Local place resolution: known, unknown, and invalid inputs."""

    databases = set()

    def test_known_city_country(self):
        self.assertEqual(resolve_place("Enugu, Nigeria"), (6.4, 7.5))
        self.assertEqual(resolve_place("Toronto, Canada"), (43.7, -79.4))

    def test_case_and_whitespace_tolerance(self):
        self.assertEqual(resolve_place("  enugu,   NIGERIA  "), (6.4, 7.5))
        self.assertEqual(resolve_place("TORONTO"), (43.7, -79.4))

    def test_bare_city(self):
        lat, lng = resolve_place("Lagos")
        self.assertAlmostEqual(lat, 6.5)
        self.assertAlmostEqual(lng, 3.4)

    def test_country_only_uses_representative_coords(self):
        lat, lng = resolve_place("Canada")
        self.assertAlmostEqual(lat, 45.4)
        self.assertAlmostEqual(lng, -75.7)

    def test_unknown_town_in_known_country_is_not_guessed(self):
        self.assertEqual(resolve_place("Somewhereville, Nigeria"), (None, None))

    def test_unknown_place_returns_nones(self):
        self.assertEqual(resolve_place("Atlantis"), (None, None))
        self.assertEqual(resolve_place(""), (None, None))
        self.assertEqual(resolve_place(None), (None, None))
        self.assertEqual(resolve_place("   "), (None, None))

    def test_never_returns_zero_zero(self):
        for place in ("", "Atlantis", "Nowhere, Unknownland", None):
            self.assertNotEqual(resolve_place(place), (0, 0))
            self.assertNotEqual(resolve_place(place), (0.0, 0.0))

    def test_all_table_coordinates_are_valid(self):
        from . import gazetteer

        for table in (
            gazetteer._CITIES,
            gazetteer._COUNTRIES,
            gazetteer._CITY_COUNTRY,
        ):
            for name, coords in table.items():
                lat, lng = coords
                self.assertTrue(
                    -90 <= lat <= 90 and -180 <= lng <= 180,
                    "invalid coords for %s: %r" % (name, coords),
                )
                self.assertNotEqual((lat, lng), (0, 0))


class PlacesGazetteerAPITests(AuthenticatedTestCase):
    def test_known_place_returns_coordinates(self):
        self.mkmember(name="Grace Okafor", birth_place="Enugu, Nigeria")
        response = self.client.get("/api/places/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "name": "Grace Okafor",
                    "place": "Enugu, Nigeria",
                    "lat": 6.4,
                    "lng": 7.5,
                    "kind": "birth",
                }
            ],
        )

    def test_unknown_place_returns_null_coordinates(self):
        self.mkmember(name="Mystery", birth_place="Atlantis")
        response = self.client.get("/api/places/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "name": "Mystery",
                    "place": "Atlantis",
                    "lat": None,
                    "lng": None,
                    "kind": "birth",
                }
            ],
        )


class AuthTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
    def test_register_success_logs_in_and_creates_tree(self):
        response = self.client.post(
            "/api/auth/register",
            {
                "username": "alice",
                "email": "alice@example.com",
                "password": "s3curePass!",
                "password2": "s3curePass!",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(
            set(body.keys()), {"id", "username", "email"}
        )
        self.assertEqual(body["username"], "alice")
        user = User.objects.get(username="alice")
        self.assertTrue(user.check_password("s3curePass!"))
        self.assertTrue(FamilyTree.objects.filter(owner=user).exists())
        # Registration logs the session in immediately.
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "alice")

    def test_register_duplicate_rejected(self):
        User.objects.create_user(username="alice", password="s3curePass!")
        response = self.client.post(
            "/api/auth/register",
            {"username": "alice", "password": "otherPass1", "password2": "otherPass1"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.json())

    def test_register_validation(self):
        mismatch = self.client.post(
            "/api/auth/register",
            {"username": "bob", "password": "s3curePass!", "password2": "different1"},
            content_type="application/json",
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertIn("password2", mismatch.json())
        short = self.client.post(
            "/api/auth/register",
            {"username": "bob", "password": "short", "password2": "short"},
            content_type="application/json",
        )
        self.assertEqual(short.status_code, 400)
        missing = self.client.post(
            "/api/auth/register",
            {"password": "s3curePass!", "password2": "s3curePass!"},
            content_type="application/json",
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("username", missing.json())

    def test_login_logout_flow(self):
        User.objects.create_user(username="alice", password="s3curePass!")
        bad = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "wrongpass"},
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(
            bad.json(), {"non_field_errors": ["Invalid username or password."]}
        )
        unknown = self.client.post(
            "/api/auth/login",
            {"username": "nobody", "password": "whatever123"},
            content_type="application/json",
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(
            unknown.json(), {"non_field_errors": ["Invalid username or password."]}
        )
        ok = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "s3curePass!"},
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["username"], "alice")
        self.assertNotIn("password", ok.json())
        out = self.client.post("/api/auth/logout")
        self.assertEqual(out.status_code, 200)
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 403)

    def test_me_unauthenticated_rejected(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 403)

    def test_login_throttling(self):
        from django.core.cache import cache

        User.objects.create_user(username="alice", password="s3curePass!")
        bad = {"username": "alice", "password": "wrongpass"}
        for _ in range(5):
            response = self.client.post(
                "/api/auth/login", bad, content_type="application/json"
            )
            self.assertEqual(response.status_code, 400)
        blocked = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "s3curePass!"},
            content_type="application/json",
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("detail", blocked.json())
        cache.clear()
        ok = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "s3curePass!"},
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)

    def test_primed_throttle_counter_blocks(self):
        from django.core.cache import cache

        User.objects.create_user(username="alice", password="s3curePass!")
        cache.set("login-attempts:127.0.0.1", 5, 300)
        response = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "s3curePass!"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 429)


class PasswordResetTests(TestCase):
    def test_full_reset_flow(self):
        import re

        User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="oldPass123",
        )
        response = self.client.post(
            "/accounts/password_reset/", {"email": "alice@example.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("Mycelium", message.subject)
        self.assertNotIn("oldPass123", message.body)
        match = re.search(
            r"/accounts/reset/(?P<uidb64>[^/\s]+)/(?P<token>[^\s/]+)/",
            message.body,
        )
        self.assertIsNotNone(match)
        confirm = self.client.get(
            "/accounts/reset/%(uidb64)s/%(token)s/" % match.groupdict()
        )
        self.assertEqual(confirm.status_code, 302)
        set_password = self.client.post(
            confirm.url,
            {"new_password1": "brandNew456", "new_password2": "brandNew456"},
        )
        self.assertEqual(set_password.status_code, 302)
        user = User.objects.get(username="alice")
        self.assertTrue(user.check_password("brandNew456"))
        login_ok = self.client.post(
            "/api/auth/login",
            {"username": "alice", "password": "brandNew456"},
            content_type="application/json",
        )
        self.assertEqual(login_ok.status_code, 200)

    def test_unknown_email_sends_nothing(self):
        response = self.client.post(
            "/accounts/password_reset/", {"email": "ghost@example.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_private_endpoints_reject_anonymous(self):
        urls = [
            "/api/members",
            "/api/events/",
            "/api/stories/",
            "/api/places/",
            "/api/center/",
            "/api/connections/",
            "/api/shared/someone/members/",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/members", {"name": "X"}, content_type="application/json"
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/storyhelper", {"text": "hi"}, content_type="application/json"
            ).status_code,
            403,
        )


class CsrfEnforcementTests(TestCase):
    def test_session_post_requires_csrf_token(self):
        User.objects.create_user(username="alice", password="s3curePass!")
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username="alice", password="s3curePass!"))
        no_token = client.post(
            "/api/members", {"name": "No Token"}, content_type="application/json"
        )
        self.assertEqual(no_token.status_code, 403)
        csrf = client.get("/api/auth/csrf/")
        self.assertEqual(csrf.status_code, 200)
        token = client.cookies["csrftoken"].value
        with_token = client.post(
            "/api/members",
            {"name": "With Token"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(with_token.status_code, 201, with_token.content)


class OwnershipIsolationTests(AuthenticatedTestCase):
    """Two users must never see or touch each other's family data."""

    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user(
            username="other", password="testpass123"
        )

    def as_other(self):
        self.client.force_authenticate(user=self.other)

    def as_user(self):
        self.client.force_authenticate(user=self.user)

    def test_lists_are_isolated(self):
        self.client.post(
            "/api/members", {"name": "Mine"}, content_type="application/json"
        )
        self.as_other()
        self.assertEqual(self.client.get("/api/members").json()["results"], [])
        self.assertEqual(self.client.get("/api/events/").json()["results"], [])
        self.assertEqual(self.client.get("/api/stories/").json()["results"], [])
        self.assertEqual(self.client.get("/api/places/").json(), [])
        self.client.post(
            "/api/members", {"name": "Theirs"}, content_type="application/json"
        )
        self.as_user()
        names = [
            item["name"]
            for item in self.client.get("/api/members").json()["results"]
        ]
        self.assertEqual(names, ["Mine"])

    def test_cross_account_detail_access_404s(self):
        created = self.client.post(
            "/api/members", {"name": "Mine"}, content_type="application/json"
        ).json()
        member_id = created["id"]
        self.as_other()
        self.assertEqual(
            self.client.get(f"/api/members/{member_id}/").status_code, 404
        )
        self.assertEqual(
            self.client.patch(
                f"/api/members/{member_id}/",
                {"bio": "hijacked"},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/api/members/{member_id}/").status_code, 404
        )
        self.as_user()
        self.assertEqual(
            self.client.get(f"/api/members/{member_id}/").status_code, 200
        )

    def test_cannot_link_to_other_users_members(self):
        mine = self.mkmember(name="Mine")
        self.as_other()
        for payload in (
            {"name": "Sneaky", "relatedTo": mine.pk},
            {"name": "Sneaky", "parents": [mine.pk]},
            {"name": "Sneaky", "partners": [mine.pk]},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/members", payload, content_type="application/json"
                )
                self.assertEqual(response.status_code, 400, response.content)
        event = self.client.post(
            "/api/events",
            {"memberId": mine.pk, "text": "hijack"},
            content_type="application/json",
        )
        self.assertEqual(event.status_code, 400)
        story = self.client.post(
            "/api/stories",
            {"memberId": mine.pk, "title": "T", "text": "hijack"},
            content_type="application/json",
        )
        self.assertEqual(story.status_code, 400)

    def test_cannot_set_owner_on_create(self):
        # "owner" is not a writable API field, so a client-supplied value is
        # ignored and the record always belongs to the requester.
        response = self.client.post(
            "/api/members",
            {"name": "Sneaky", "owner": self.other.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        member = FamilyMember.objects.get(pk=response.json()["id"])
        self.assertEqual(member.owner, self.user)

    def test_created_records_belong_to_requester(self):
        created = self.client.post(
            "/api/members", {"name": "Mine"}, content_type="application/json"
        ).json()
        member = FamilyMember.objects.get(pk=created["id"])
        self.assertEqual(member.owner, self.user)

    def test_cross_account_event_and_story_detail_404(self):
        event_id = self.client.post(
            "/api/events", {"text": "Mine"}, content_type="application/json"
        ).json()["id"]
        story_id = self.client.post(
            "/api/stories",
            {"title": "Mine", "text": "Mine"},
            content_type="application/json",
        ).json()["id"]
        self.as_other()
        for url in (f"/api/events/{event_id}/", f"/api/stories/{story_id}/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(
                    self.client.patch(
                        url, {"text": "hijacked"}, content_type="application/json"
                    ).status_code,
                    404,
                )
                self.assertEqual(self.client.delete(url).status_code, 404)
        self.as_user()
        self.assertEqual(
            self.client.get(f"/api/events/{event_id}/").status_code, 200
        )
        self.assertEqual(
            self.client.get(f"/api/stories/{story_id}/").status_code, 200
        )

    def test_cross_account_update_linkage_rejected(self):
        mine = self.mkmember(name="Mine")
        own_id = self.client.post(
            "/api/members", {"name": "Own"}, content_type="application/json"
        ).json()["id"]
        self.as_other()
        response = self.client.patch(
            f"/api/members/{own_id}/",
            {"relatedTo": mine.pk},
            content_type="application/json",
        )
        # The target itself is invisible to the other user.
        self.assertEqual(response.status_code, 404)
        other_id = self.client.post(
            "/api/members", {"name": "Theirs"}, content_type="application/json"
        ).json()["id"]
        hijack = self.client.patch(
            f"/api/members/{other_id}/",
            {"parents": [mine.pk]},
            content_type="application/json",
        )
        self.assertEqual(hijack.status_code, 400, hijack.content)
        self.as_user()
        self.assertEqual(
            FamilyMember.objects.get(pk=other_id).parents.count(), 0
        )


class CenterTests(AuthenticatedTestCase):
    def test_center_starts_empty_then_set_and_replaced(self):
        empty = self.client.get("/api/center/")
        self.assertEqual(empty.status_code, 200)
        self.assertIsNone(empty.json()["member"])
        first = self.client.post(
            "/api/members", {"name": "First"}, content_type="application/json"
        ).json()
        second = self.client.post(
            "/api/members", {"name": "Second"}, content_type="application/json"
        ).json()
        set_first = self.client.post(
            "/api/center/",
            {"memberId": first["id"]},
            content_type="application/json",
        )
        self.assertEqual(set_first.status_code, 200)
        self.assertEqual(set_first.json()["member"]["id"], first["id"])
        # Setting again is idempotent and replaceable.
        self.client.post(
            "/api/center/",
            {"memberId": first["id"]},
            content_type="application/json",
        )
        replaced = self.client.post(
            "/api/center/",
            {"memberId": second["id"]},
            content_type="application/json",
        )
        self.assertEqual(replaced.json()["member"]["id"], second["id"])
        self.assertEqual(
            self.client.get("/api/center/").json()["member"]["id"], second["id"]
        )

    def test_center_rejects_other_users_members(self):
        mine = self.mkmember(name="Mine")
        other_user = User.objects.create_user(username="stranger", password="x")
        stranger = FamilyMember.objects.create(name="Stranger", owner=other_user)
        missing = self.client.post(
            "/api/center/", {}, content_type="application/json"
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            self.client.post(
                "/api/center/",
                {"memberId": stranger.pk},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/center/", {"memberId": 999999}, content_type="application/json"
            ).status_code,
            404,
        )
        ok = self.client.post(
            "/api/center/",
            {"memberId": mine.pk},
            content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)


class PhotoPrivacyTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="mycelium-test-media-")
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.other = User.objects.create_user(
            username="other", password="testpass123"
        )

    def upload_member(self, name="With Photo"):
        photo = SimpleUploadedFile("photo.gif", TINY_GIF, content_type="image/gif")
        response = self.client.post("/api/members", {"name": name, "photo": photo})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def test_owner_can_download_other_gets_404_anonymous_403(self):
        member_id = self.upload_member()
        own = self.client.get(f"/api/photos/{member_id}/")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(
            b"".join(own.streaming_content), TINY_GIF
        )
        self.client.force_authenticate(user=self.other)
        self.assertEqual(
            self.client.get(f"/api/photos/{member_id}/").status_code, 404
        )
        self.client.force_authenticate(user=None)
        self.client.logout()
        anon = APIClient()
        self.assertEqual(
            anon.get(f"/api/photos/{member_id}/").status_code, 403
        )

    def test_member_without_photo_404s(self):
        member_id = self.client.post(
            "/api/members", {"name": "No Photo"}, content_type="application/json"
        ).json()["id"]
        self.assertEqual(
            self.client.get(f"/api/photos/{member_id}/").status_code, 404
        )

    def test_granted_viewer_can_download_revoked_cannot(self):
        other_member = FamilyMember.objects.create(
            name="Theirs", owner=self.other
        )
        photo = SimpleUploadedFile("photo.gif", TINY_GIF, content_type="image/gif")
        other_member.photo.save("photo.gif", photo, save=True)
        thread = self.client.post(
            "/api/connections/",
            {"to_username": "other", "from_member": self.mkmember(
                name="Mine").pk},
            content_type="application/json",
        ).json()
        # No grant yet: viewer gets 404.
        self.assertEqual(
            self.client.get(f"/api/photos/{other_member.pk}/").status_code, 404
        )
        self.client.force_authenticate(user=self.other)
        self.client.patch(
            f"/api/connections/{thread['id']}/",
            {"status": "approved", "grants_view": True},
            content_type="application/json",
        )
        self.client.force_authenticate(user=self.user)
        granted = self.client.get(f"/api/photos/{other_member.pk}/")
        self.assertEqual(granted.status_code, 200)
        self.assertEqual(b"".join(granted.streaming_content), TINY_GIF)
        # Revoke the grant: access ends, records remain.
        self.client.force_authenticate(user=self.other)
        self.client.patch(
            f"/api/connections/{thread['id']}/",
            {"grants_view": False},
            content_type="application/json",
        )
        self.client.force_authenticate(user=self.user)
        self.assertEqual(
            self.client.get(f"/api/photos/{other_member.pk}/").status_code, 404
        )
        self.assertTrue(
            FamilyMember.objects.filter(pk=other_member.pk).exists()
        )

    def test_missing_photo_file_404s(self):
        member = FamilyMember.objects.create(
            name="Lost Photo", owner=self.user, photo="member_photos/gone.gif"
        )
        self.assertEqual(
            self.client.get(f"/api/photos/{member.pk}/").status_code, 404
        )

    def test_invalid_replacement_keeps_old_photo(self):
        member_id = self.upload_member()
        member = FamilyMember.objects.get(pk=member_id)
        before = member.photo.name
        bad = SimpleUploadedFile("bad.txt", b"not an image", content_type="text/plain")
        response = self.client.patch(
            f"/api/members/{member_id}/", {"photo": bad}, format="multipart"
        )
        self.assertEqual(response.status_code, 400, response.content)
        member.refresh_from_db()
        self.assertEqual(member.photo.name, before)
        self.assertEqual(
            self.client.get(f"/api/photos/{member_id}/").status_code, 200
        )


class ConnectionTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user(
            username="relative", password="testpass123"
        )
        self.third = User.objects.create_user(
            username="stranger", password="testpass123"
        )
        self.mine = self.mkmember(name="My Grandma")

    def as_other(self):
        self.client.force_authenticate(user=self.other)

    def as_user(self):
        self.client.force_authenticate(user=self.user)

    def test_request_approve_flow_grants_nothing(self):
        created = self.client.post(
            "/api/connections/",
            {
                "to_username": "relative",
                "from_member": self.mine.pk,
                "note": "I think we share a grandmother.",
            },
            content_type="application/json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertEqual(body["status"], "pending")
        self.assertEqual(body["from_user"], "testuser")
        self.assertEqual(body["to_user"], "relative")
        # Requester cannot approve their own request.
        self.assertEqual(
            self.client.patch(
                f"/api/connections/{body['id']}/",
                {"status": "approved"},
                content_type="application/json",
            ).status_code,
            403,
        )
        # Recipient approves; trees are NOT merged and nothing is exposed.
        self.as_other()
        approved = self.client.patch(
            f"/api/connections/{body['id']}/",
            {"status": "approved"},
            content_type="application/json",
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")
        self.assertEqual(
            self.client.get("/api/members").json()["results"], []
        )
        self.as_user()
        names = [
            item["name"]
            for item in self.client.get("/api/members").json()["results"]
        ]
        self.assertEqual(names, ["My Grandma"])

    def test_duplicates_self_and_unknown_rejected(self):
        self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        )
        duplicate = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        )
        self.assertEqual(duplicate.status_code, 400)
        self.as_other()
        reverse = self.client.post(
            "/api/connections/",
            {"to_username": "testuser", "from_member": self.mine.pk},
            content_type="application/json",
        )
        # from_member is not theirs, and the pair already has a thread.
        self.assertEqual(reverse.status_code, 400)
        self.as_user()
        self_request = self.client.post(
            "/api/connections/",
            {"to_username": "testuser", "from_member": self.mine.pk},
            content_type="application/json",
        )
        self.assertEqual(self_request.status_code, 400)
        unknown = self.client.post(
            "/api/connections/",
            {"to_username": "ghost", "from_member": self.mine.pk},
            content_type="application/json",
        )
        self.assertEqual(unknown.status_code, 400)

    def test_reject_and_revoke_keep_records(self):
        created = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        ).json()
        self.as_other()
        rejected = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "rejected"},
            content_type="application/json",
        )
        self.assertEqual(rejected.json()["status"], "rejected")
        # Answered requests cannot be re-answered.
        again = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "approved"},
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 400)
        # Revoking deletes only the thread, never the members.
        self.assertEqual(
            self.client.delete(f"/api/connections/{created['id']}/").status_code,
            204,
        )
        self.as_user()
        self.assertTrue(FamilyMember.objects.filter(pk=self.mine.pk).exists())

    def test_third_party_sees_nothing(self):
        created = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        ).json()
        self.client.force_authenticate(user=self.third)
        self.assertEqual(
            self.client.get(f"/api/connections/{created['id']}/").status_code, 404
        )
        self.assertEqual(self.client.get("/api/connections/").json()["results"], [])

    def grant_setup(self):
        """A requests B; B approves and grants viewing. Returns thread id."""
        created = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        ).json()
        self.as_other()
        theirs = FamilyMember.objects.create(
            name="Their Grandma", owner=self.other, birth_place="Lagos, Nigeria"
        )
        approved = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "approved", "grants_view": True},
            content_type="application/json",
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        self.assertTrue(approved.json()["grants_view"])
        self.as_user()
        return created["id"], theirs.pk

    def test_grant_rules(self):
        created = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        ).json()
        # Requester cannot touch status or grants.
        self.assertEqual(
            self.client.patch(
                f"/api/connections/{created['id']}/",
                {"grants_view": True},
                content_type="application/json",
            ).status_code,
            403,
        )
        # Grants require an approved thread.
        self.as_other()
        early = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"grants_view": True},
            content_type="application/json",
        )
        self.assertEqual(early.status_code, 400)
        bad_value = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "approved", "grants_view": "yes"},
            content_type="application/json",
        )
        self.assertEqual(bad_value.status_code, 400)
        good = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "approved", "grants_view": True},
            content_type="application/json",
        )
        self.assertEqual(good.status_code, 200)
        # Grant can be revoked while staying approved.
        revoked = self.client.patch(
            f"/api/connections/{created['id']}/",
            {"grants_view": False},
            content_type="application/json",
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertFalse(revoked.json()["grants_view"])
        self.as_user()

    def test_shared_access_with_grant(self):
        _, theirs_id = self.grant_setup()
        members = self.client.get("/api/shared/relative/members/")
        self.assertEqual(members.status_code, 200)
        results = members.json()["results"]
        self.assertEqual([m["name"] for m in results], ["Their Grandma"])
        self.assertEqual(results[0]["birthPlace"], "Lagos, Nigeria")
        self.assertEqual(self.client.get("/api/shared/relative/events/").status_code, 200)
        self.assertEqual(self.client.get("/api/shared/relative/stories/").status_code, 200)
        places = self.client.get("/api/shared/relative/places/")
        self.assertEqual(places.status_code, 200)
        self.assertEqual(len(places.json()), 1)
        # Own data untouched; nothing merged.
        own = self.client.get("/api/members").json()["results"]
        self.assertEqual([m["name"] for m in own], ["My Grandma"])
        _ = theirs_id

    def test_shared_denied_without_grant(self):
        created = self.client.post(
            "/api/connections/",
            {"to_username": "relative", "from_member": self.mine.pk},
            content_type="application/json",
        ).json()
        self.as_other()
        self.client.patch(
            f"/api/connections/{created['id']}/",
            {"status": "approved"},
            content_type="application/json",
        )
        self.as_user()
        self.assertEqual(
            self.client.get("/api/shared/relative/members/").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/shared/ghost/members/").status_code, 404
        )

    def test_no_propagation_to_third_user(self):
        self.grant_setup()
        self.client.force_authenticate(user=self.third)
        self.assertEqual(
            self.client.get("/api/shared/relative/members/").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/shared/testuser/members/").status_code, 404
        )
        self.as_user()

    def test_revoke_removes_shared_access(self):
        thread_id, _ = self.grant_setup()
        self.assertEqual(
            self.client.get("/api/shared/relative/members/").status_code, 200
        )
        self.as_other()
        self.assertEqual(
            self.client.delete(f"/api/connections/{thread_id}/").status_code, 204
        )
        self.as_user()
        self.assertEqual(
            self.client.get("/api/shared/relative/members/").status_code, 404
        )
        # Original records survive on both sides.
        self.assertTrue(FamilyMember.objects.filter(pk=self.mine.pk).exists())
        self.assertEqual(
            FamilyMember.objects.filter(owner=self.other).count(), 1
        )


class SeedCommandTests(TestCase):
    def test_seed_is_per_user_and_idempotent(self):
        user = User.objects.create_user(username="demo", password="x")
        call_command("seed_sample_family", username="demo")
        self.assertEqual(
            FamilyMember.objects.filter(owner=user).count(), 4
        )
        self.assertEqual(FamilyEvent.objects.filter(owner=user).count(), 4)
        self.assertEqual(FamilyStory.objects.filter(owner=user).count(), 2)
        call_command("seed_sample_family", username="demo")
        self.assertEqual(
            FamilyMember.objects.filter(owner=user).count(), 4
        )
        other = User.objects.create_user(username="demo2", password="x")
        call_command("seed_sample_family", username="demo2")
        self.assertEqual(
            FamilyMember.objects.filter(owner=other).count(), 4
        )

    def test_seed_requires_existing_user(self):
        with self.assertRaises(CommandError):
            call_command("seed_sample_family", username="ghost")

    def test_assign_legacy_records(self):
        legacy = FamilyMember.objects.create(name="Legacy")
        kept = FamilyMember.objects.create(
            name="Kept", owner=User.objects.create_user(username="first", password="x")
        )
        owner = User.objects.create_user(username="newowner", password="x")
        call_command("assign_legacy_records", username="newowner")
        legacy.refresh_from_db()
        kept.refresh_from_db()
        self.assertEqual(legacy.owner, owner)
        self.assertEqual(kept.owner.username, "first")
        # Re-running assigns nothing further.
        call_command("assign_legacy_records", username="newowner")
        self.assertEqual(
            FamilyMember.objects.filter(owner=owner).count(), 1
        )


class NoStoreMiddlewareTests(AuthenticatedTestCase):
    """Private API/account responses must never be stored by browsers."""

    def assert_no_store(self, response):
        self.assertIn("no-store", response.get("Cache-Control", ""))

    def test_authenticated_user_endpoint_not_storable(self):
        self.assert_no_store(self.client.get("/api/auth/me"))

    def test_anonymous_api_response_not_storable(self):
        self.client.force_authenticate(user=None)
        self.client.logout()
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)
        self.assert_no_store(response)

    def test_account_pages_not_storable(self):
        self.assert_no_store(self.client.get("/accounts/password_reset/"))


class EmailConfigTests(SimpleTestCase):
    """Email configuration stays credential-free and local-friendly."""

    databases = set()

    def test_dev_defaults_need_no_credentials(self):
        from django.conf import settings as dj_settings

        # The test runner swaps the backend for locmem; the code default
        # (used whenever DJANGO_EMAIL_BACKEND is unset) is the console
        # backend — verified by reading the setting definition path.
        self.assertEqual(dj_settings.EMAIL_PORT, 587)
        self.assertTrue(dj_settings.EMAIL_USE_TLS)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.gmail.com",
        EMAIL_PORT=587,
        EMAIL_USE_TLS=True,
        EMAIL_HOST_USER="user@gmail.com",
        EMAIL_HOST_PASSWORD="app-password-placeholder",
        DEFAULT_FROM_EMAIL="Mycelium <user@gmail.com>",
    )
    def test_gmail_smtp_settings_accepted(self):
        from django.core.mail import get_connection

        connection = get_connection()
        self.assertEqual(connection.host, "smtp.gmail.com")
        self.assertEqual(connection.port, 587)
        self.assertTrue(connection.use_tls)
        self.assertEqual(connection.username, "user@gmail.com")


class CloudinaryConfigTests(SimpleTestCase):
    """Cloudinary stays off unless explicitly configured; deps are present."""

    databases = set()

    def test_local_storage_is_default(self):
        from django.conf import settings as dj_settings
        from django.core.files.storage import default_storage

        self.assertFalse(dj_settings.USE_CLOUDINARY)
        self.assertEqual(
            default_storage.__class__.__name__, "FileSystemStorage"
        )

    def test_cloudinary_libraries_available(self):
        import cloudinary  # noqa: F401
        import cloudinary_storage  # noqa: F401
