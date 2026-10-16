"""Serializers for the family app.

The JSON contract uses the frontend's camelCase property names (``birthDate``,
``relatedTo``, ``memberId``, ``photoUrl``, ...). Internally the models use
idiomatic Django snake_case names; ``source=`` maps between the two.

The frontend submits ``FormData`` where empty inputs arrive as ``""``. The
``EmptyStringToNone`` mixin converts those to ``None`` for nullable fields so
that "no value" validates cleanly instead of failing date/integer parsing.
"""

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.urls import reverse
from rest_framework import serializers

from .models import (
    FamilyEvent,
    FamilyMember,
    FamilyStory,
    RelativeConnection,
)


class EmptyStringToNoneMixin:
    """Convert ``""`` to ``None`` for the given nullable input keys.

    Works for both JSON bodies and multipart ``QueryDict`` payloads.
    """

    empty_to_none_keys = ()

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)
        for key in self.empty_to_none_keys:
            try:
                value = data.get(key)
            except AttributeError:
                continue
            if value == "":
                data[key] = None
        return super().to_internal_value(data)


class OwnedMemberReferencesMixin:
    """Narrow member-reference querysets to the requesting user's members.

    Cross-account IDs then fail with the same generic "invalid pk" error as
    nonexistent IDs, so update/create paths cannot probe other users' trees.
    Without an authenticated request context, nothing is selectable.
    """

    owned_member_fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            queryset = FamilyMember.objects.filter(owner=user)
        else:
            queryset = FamilyMember.objects.none()
        for name in self.owned_member_fields:
            field = self.fields[name]
            target = getattr(field, "child_relation", field)
            target.queryset = queryset


class OptionalMemberField(serializers.PrimaryKeyRelatedField):
    """Member reference that also accepts ``""``/missing as "nobody"."""

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_null", True)
        kwargs.setdefault("required", False)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        if data in ("", None):
            return None
        return super().to_internal_value(data)


def apply_relationship_hint(member):
    """Derive canonical ``parents``/``partners`` links from the entry hint.

    Only adds links; M2M ``add()`` is idempotent so re-applying never creates
    duplicates. Self-links are filtered out so inconsistent input cannot
    corrupt the graph. Labels without an unambiguous mapping (Me,
    Grandchild, Aunt / Uncle, Cousin, Other, blank) keep the hint only.
    """
    label = member.relationship_label
    other = member.related_to
    if not label or other is None or other.pk == member.pk:
        return

    def safe_add(relation, *people):
        # Never link a member to themselves; compare against the owner of
        # the relation being modified, not against the member being saved.
        owner_pk = relation.instance.pk
        for person in people:
            if person.pk != owner_pk:
                relation.add(person)

    if label == FamilyMember.RELATIONSHIP_PARENT:
        # This member is a parent of `other`.
        safe_add(other.parents, member)
    elif label == FamilyMember.RELATIONSHIP_CHILD:
        # This member is a child of `other`.
        safe_add(member.parents, other)
    elif label == FamilyMember.RELATIONSHIP_SPOUSE:
        safe_add(member.partners, other)
    elif label == FamilyMember.RELATIONSHIP_SIBLING:
        # Share `other`'s parents (if any are recorded).
        safe_add(member.parents, *other.parents.all())
    elif label == FamilyMember.RELATIONSHIP_GRANDPARENT:
        # This member is a parent of `other`'s parents (if recorded).
        for parent in other.parents.all():
            safe_add(parent.parents, member)


class FamilyMemberSerializer(
    OwnedMemberReferencesMixin, EmptyStringToNoneMixin, serializers.ModelSerializer
):
    empty_to_none_keys = ("birthDate", "deathDate", "relatedTo")
    owned_member_fields = ("relatedTo", "parents", "partners")

    birthDate = serializers.DateField(
        source="birth_date", required=False, allow_null=True
    )
    deathDate = serializers.DateField(
        source="death_date", required=False, allow_null=True
    )
    birthPlace = serializers.CharField(
        source="birth_place", required=False, allow_blank=True, default=""
    )
    livedPlace = serializers.CharField(
        source="lived_place", required=False, allow_blank=True, default=""
    )
    relationship = serializers.ChoiceField(
        source="relationship_label",
        choices=FamilyMember.RELATIONSHIP_CHOICES,
        required=False,
        allow_blank=True,
        default="",
    )
    relatedTo = OptionalMemberField(
        source="related_to", queryset=FamilyMember.objects.all()
    )
    parents = serializers.PrimaryKeyRelatedField(
        many=True, queryset=FamilyMember.objects.all(), required=False
    )
    partners = serializers.PrimaryKeyRelatedField(
        many=True, queryset=FamilyMember.objects.all(), required=False
    )
    spouseId = serializers.SerializerMethodField()
    photoUrl = serializers.SerializerMethodField()

    class Meta:
        model = FamilyMember
        fields = [
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
            "photo",
            "photoUrl",
            "bio",
        ]
        extra_kwargs = {
            "bio": {"required": False, "allow_blank": True},
            "photo": {"required": False, "allow_null": True},
        }

    def get_spouseId(self, obj):
        spouse = obj.spouse
        return spouse.pk if spouse is not None else None

    def get_photoUrl(self, obj):
        if not obj.photo:
            return None
        # Photos are served through an ownership-checked endpoint, never
        # through a public media URL.
        path = reverse("family:member-photo", kwargs={"pk": obj.pk})
        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(path)
        return path

    def validate(self, attrs):
        birth = attrs.get(
            "birth_date",
            getattr(self.instance, "birth_date", None),
        )
        death = attrs.get(
            "death_date",
            getattr(self.instance, "death_date", None),
        )
        if birth and death and death < birth:
            raise serializers.ValidationError(
                {"deathDate": "Death date cannot be earlier than birth date."}
            )

        related = attrs.get("related_to", getattr(self.instance, "related_to", None))
        if (
            related is not None
            and self.instance is not None
            and related.pk == self.instance.pk
        ):
            raise serializers.ValidationError(
                {"relatedTo": "A member cannot be related to themselves."}
            )

        for key, api_name in (("parents", "parents"), ("partners", "partners")):
            if key in attrs and self.instance is not None:
                pks = {person.pk for person in attrs[key]}
                if self.instance.pk in pks:
                    raise serializers.ValidationError(
                        {api_name: "A member cannot be linked to themselves."}
                    )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        parents = validated_data.pop("parents", None)
        partners = validated_data.pop("partners", None)
        member = FamilyMember.objects.create(**validated_data)
        if parents is not None:
            member.parents.set(p for p in parents if p.pk != member.pk)
        if partners is not None:
            member.partners.set(p for p in partners if p.pk != member.pk)
        apply_relationship_hint(member)
        return member

    @transaction.atomic
    def update(self, instance, validated_data):
        parents = validated_data.pop("parents", None)
        partners = validated_data.pop("partners", None)
        member = super().update(instance, validated_data)
        if parents is not None:
            member.parents.set(p for p in parents if p.pk != member.pk)
        if partners is not None:
            member.partners.set(p for p in partners if p.pk != member.pk)
        apply_relationship_hint(member)
        return member


class FamilyEventSerializer(
    OwnedMemberReferencesMixin, EmptyStringToNoneMixin, serializers.ModelSerializer
):
    empty_to_none_keys = ("memberId", "year")
    owned_member_fields = ("memberId",)

    memberId = OptionalMemberField(source="member", queryset=FamilyMember.objects.all())
    year = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = FamilyEvent
        fields = ["id", "memberId", "year", "text"]


class FamilyStorySerializer(
    OwnedMemberReferencesMixin, EmptyStringToNoneMixin, serializers.ModelSerializer
):
    empty_to_none_keys = ("memberId",)
    owned_member_fields = ("memberId",)

    memberId = OptionalMemberField(source="member", queryset=FamilyMember.objects.all())

    class Meta:
        model = FamilyStory
        fields = ["id", "memberId", "title", "author", "category", "text"]
        extra_kwargs = {
            "author": {"required": False, "allow_blank": True},
        }


class StoryHelperSerializer(serializers.Serializer):
    """Input contract for POST /api/storyhelper/."""

    text = serializers.CharField(max_length=5000, allow_blank=False, trim_whitespace=True)
    title = serializers.CharField(
        max_length=200, required=False, allow_blank=True, default=""
    )

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Story text is required.")
        return value.strip()


class RegisterSerializer(serializers.Serializer):
    """Account registration. Passwords are hashed by Django, never stored."""

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    password2 = serializers.CharField(write_only=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError(
                "An account with that username already exists."
            )
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {"password2": "The two passwords do not match."}
            )
        try:
            validate_password(attrs["password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        from .models import FamilyTree

        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )
        FamilyTree.objects.get_or_create(owner=user)
        return user


class LoginSerializer(serializers.Serializer):
    """Credential check. Error is deliberately vague (no user enumeration)."""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = authenticate(
            request, username=attrs["username"], password=attrs["password"]
        )
        if user is None:
            raise serializers.ValidationError("Invalid username or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.")
        attrs["user"] = user
        return attrs


class RelativeConnectionSerializer(
    OwnedMemberReferencesMixin, serializers.ModelSerializer
):
    owned_member_fields = ("from_member",)
    from_user = serializers.CharField(source="from_user.username", read_only=True)
    to_user = serializers.CharField(source="to_user.username", read_only=True)
    to_username = serializers.CharField(write_only=True)

    class Meta:
        model = RelativeConnection
        fields = [
            "id",
            "from_user",
            "to_user",
            "to_username",
            "from_member",
            "note",
            "status",
            "grants_view",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "grants_view", "created_at", "updated_at"]
        extra_kwargs = {
            "note": {"required": False, "allow_blank": True},
        }

    def validate_to_username(self, value):
        request = self.context.get("request")
        try:
            target = User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "No registered user with that username."
            )
        if request is not None and target == request.user:
            raise serializers.ValidationError("You cannot connect to yourself.")
        return value

    def validate(self, attrs):
        from django.db.models import Q

        request = self.context.get("request")
        user = getattr(request, "user", None)
        target = User.objects.filter(username=attrs["to_username"]).first()
        if user is not None and target is not None:
            exists = RelativeConnection.objects.filter(
                Q(from_user=user, to_user=target)
                | Q(from_user=target, to_user=user)
            ).exists()
            if exists:
                raise serializers.ValidationError(
                    "A connection between these users already exists."
                )
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        target = User.objects.get(username=validated_data.pop("to_username"))
        return RelativeConnection.objects.create(
            from_user=request.user, to_user=target, **validated_data
        )
