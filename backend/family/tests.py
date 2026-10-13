import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from .models import FamilyEvent, FamilyMember, FamilyStory
from .serializers import FamilyMemberSerializer

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


class FamilyMemberModelTests(TestCase):
    def test_str_and_ordering(self):
        FamilyMember.objects.create(name="Grace Okafor")
        FamilyMember.objects.create(name="Amara Okafor")
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
        member = FamilyMember.objects.create(name="Narcissus")
        member.related_to = member
        with self.assertRaises(ValidationError):
            member.full_clean()

    def test_siblings_derived_from_shared_parent(self):
        parent = FamilyMember.objects.create(name="Amara Okafor")
        child_a = FamilyMember.objects.create(name="Grace Okafor")
        child_b = FamilyMember.objects.create(name="Samuel Okafor")
        outsider = FamilyMember.objects.create(name="James Lin")
        child_a.parents.add(parent)
        child_b.parents.add(parent)
        self.assertEqual(list(child_a.siblings), [child_b])
        self.assertEqual(list(child_b.siblings), [child_a])
        self.assertEqual(list(outsider.siblings), [])

    def test_spouse_defaults_to_none(self):
        member = FamilyMember.objects.create(name="Solo")
        self.assertIsNone(member.spouse)

    def test_spouse_returns_first_partner(self):
        anna = FamilyMember.objects.create(name="Anna")
        ben = FamilyMember.objects.create(name="Ben")
        anna.partners.add(ben)
        self.assertEqual(anna.spouse, ben)
        self.assertEqual(ben.spouse, anna)


class RelationshipDerivationTests(TestCase):
    def test_parent_hint_links_other_as_child(self):
        child = FamilyMember.objects.create(name="Grace Okafor")
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
        parent = FamilyMember.objects.create(name="Amara Okafor")
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
        existing = FamilyMember.objects.create(name="David Okafor")
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
        parent = FamilyMember.objects.create(name="Amara Okafor")
        sibling = FamilyMember.objects.create(name="Grace Okafor")
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
        parent = FamilyMember.objects.create(name="Grace Okafor")
        child = FamilyMember.objects.create(name="Maya Lin")
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
        existing = FamilyMember.objects.create(name="David Okafor")
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
        existing = FamilyMember.objects.create(name="David Okafor")
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
        member = FamilyMember.objects.create(name="Narcissus")
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


class FamilyMemberSerializerTests(TestCase):
    def test_camel_case_contract_shape(self):
        parent = FamilyMember.objects.create(name="Amara Okafor")
        member = FamilyMember.objects.create(
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


class MemberAPITests(TestCase):
    def test_list_contract_shape(self):
        parent = FamilyMember.objects.create(
            name="Amara Okafor", birth_place="Enugu, Nigeria"
        )
        child = FamilyMember.objects.create(
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
        self.assertIn("member_photos", photo_url)

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


class EventAPITests(TestCase):
    def test_create_and_list_ordered_by_year(self):
        member = FamilyMember.objects.create(name="Grace Okafor")
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


class StoryAPITests(TestCase):
    def test_create_full_story(self):
        member = FamilyMember.objects.create(name="Grace Okafor")
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


class PlacesAPITests(TestCase):
    def test_empty_database_returns_empty_list(self):
        response = self.client.get("/api/places")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_birth_and_lived_places_listed(self):
        FamilyMember.objects.create(
            name="Grace Okafor",
            birth_place="Enugu, Nigeria",
            lived_place="Toronto, Canada",
        )
        FamilyMember.objects.create(name="Nowhere Person")
        response = self.client.get("/api/places/")
        self.assertEqual(response.status_code, 200)
        places = response.json()
        self.assertEqual(len(places), 2)
        self.assertEqual(
            places[0],
            {
                "name": "Grace Okafor",
                "place": "Enugu, Nigeria",
                "lat": None,
                "lng": None,
                "kind": "birth",
            },
        )
        self.assertEqual(places[1]["kind"], "lived")
        self.assertEqual(places[1]["place"], "Toronto, Canada")


class StoryHelperTests(TestCase):
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
