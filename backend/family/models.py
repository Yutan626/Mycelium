from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class FamilyTree(models.Model):
    """One personal tree per account (created automatically at registration).

    Isolates future sharing/permission decisions: basic ownership lives on
    the records themselves (``owner``), while this row anchors per-account
    state such as the designated center person.
    """

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="family_tree",
    )
    name = models.CharField(max_length=200, blank=True, default="")
    center_member = models.ForeignKey(
        "FamilyMember",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.owner}'s family tree"


class FamilyMember(models.Model):
    """A person in the family tree.

    Relationship design (single source of truth, no redundant storage):

    * ``parents`` — directed self link (``symmetrical=False``). Adding a
      parent automatically makes this member appear in their ``children``.
      Supports any number of parents (biological, adoptive, step).
    * ``partners`` — mutual self link (``symmetrical=True``). One row
      represents both directions, so spouse/partner links can never disagree.
    * Siblings are **derived**, never stored: members sharing a parent.
    * ``relationship_label`` + ``related_to`` keep the frontend's entry hint
      ("Mother", related to X). Canonical ``parents``/``partners`` links are
      derived from that hint at the serializer layer when unambiguous.
    """

    RELATIONSHIP_ME = "Me"
    RELATIONSHIP_PARENT = "Parent"
    RELATIONSHIP_CHILD = "Child"
    RELATIONSHIP_SPOUSE = "Spouse / partner"
    RELATIONSHIP_SIBLING = "Sibling"
    RELATIONSHIP_GRANDPARENT = "Grandparent"
    RELATIONSHIP_GRANDCHILD = "Grandchild"
    RELATIONSHIP_AUNT_UNCLE = "Aunt / Uncle"
    RELATIONSHIP_COUSIN = "Cousin"
    RELATIONSHIP_OTHER = "Other"

    RELATIONSHIP_CHOICES = [
        (RELATIONSHIP_ME, "Me"),
        (RELATIONSHIP_PARENT, "Parent"),
        (RELATIONSHIP_CHILD, "Child"),
        (RELATIONSHIP_SPOUSE, "Spouse / partner"),
        (RELATIONSHIP_SIBLING, "Sibling"),
        (RELATIONSHIP_GRANDPARENT, "Grandparent"),
        (RELATIONSHIP_GRANDCHILD, "Grandchild"),
        (RELATIONSHIP_AUNT_UNCLE, "Aunt / Uncle"),
        (RELATIONSHIP_COUSIN, "Cousin"),
        (RELATIONSHIP_OTHER, "Other"),
    ]

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="family_members",
        help_text="Account that owns this record. Null only for legacy rows "
        "created before ownership existed; new records always set it.",
    )
    birth_date = models.DateField(null=True, blank=True)
    death_date = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=200, blank=True)
    lived_place = models.CharField(max_length=200, blank=True)
    relationship_label = models.CharField(
        max_length=30, choices=RELATIONSHIP_CHOICES, blank=True, default=""
    )
    related_to = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="related_members",
    )
    parents = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="children"
    )
    partners = models.ManyToManyField("self", symmetrical=True, blank=True)
    photo = models.ImageField(upload_to="member_photos/", null=True, blank=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.birth_date and self.death_date and self.death_date < self.birth_date:
            raise ValidationError(
                {"death_date": "Death date cannot be earlier than birth date."}
            )
        if self.related_to_id is not None and self.related_to_id == self.pk:
            raise ValidationError(
                {"related_to": "A member cannot be related to themselves."}
            )

    @property
    def siblings(self):
        """Members sharing at least one parent (derived, never stored)."""
        if self.pk is None:
            return FamilyMember.objects.none()
        return (
            FamilyMember.objects.filter(parents__in=self.parents.all())
            .exclude(pk=self.pk)
            .distinct()
        )

    @property
    def spouse(self):
        """First partner, for compatibility with the ``spouseId`` contract."""
        return self.partners.order_by("id").first()


class FamilyEvent(models.Model):
    """A dated happening for the memory timeline.

    ``member`` is optional: some timeline entries (e.g. historical context)
    do not belong to a single person.
    """

    member = models.ForeignKey(
        FamilyMember,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="events",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="family_events",
    )
    year = models.IntegerField(null=True, blank=True)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["year", "id"]

    def __str__(self):
        label = self.year if self.year is not None else "undated"
        return f"{label}: {self.text[:60]}"


class FamilyStory(models.Model):
    """A story, tradition, recipe or memory from the story archive."""

    CATEGORY_TRADITION = "Tradition"
    CATEGORY_MEMORY = "Memory"
    CATEGORY_RECIPE = "Recipe"
    CATEGORY_OTHER = "Other"

    CATEGORY_CHOICES = [
        (CATEGORY_TRADITION, "Tradition"),
        (CATEGORY_MEMORY, "Memory"),
        (CATEGORY_RECIPE, "Recipe"),
        (CATEGORY_OTHER, "Other"),
    ]

    member = models.ForeignKey(
        FamilyMember,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="stories",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="family_stories",
    )
    title = models.CharField(max_length=200)
    author = models.CharField(max_length=200, blank=True, default="")
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_MEMORY
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title


class RelativeConnection(models.Model):
    """A deliberate relative link between two accounts.

    Minimal, private-by-default foundation for a future request/approve
    flow. Approving a connection records the link only — it grants no
    viewing, edit, or delete rights, merges no trees, and exposes no
    private records. Either account can remove the link at any time, which
    deletes only the link, never the underlying family records.
    """

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connections_sent",
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connections_received",
    )
    from_member = models.ForeignKey(
        FamilyMember,
        on_delete=models.CASCADE,
        related_name="connection_links",
        help_text="The requester's own member record this link is about.",
    )
    note = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["from_user", "to_user"],
                name="unique_connection_per_user_pair",
            ),
        ]

    def __str__(self):
        return f"{self.from_user} -> {self.to_user} ({self.status})"
