"""Load a small demonstration family (idempotent, per-user).

Usage (only on an empty/demo database — never on a real user database):

    python manage.py seed_sample_family --username demo

The user must already exist; the command never creates accounts and never
uses a default password. All records are owned by that user.

Safety rules:

* Every record is created with ``get_or_create`` on natural keys scoped to
  the user, so repeated runs never create duplicates and never modify
  existing rows.
* Relationship links use ``ManyToMany.add()``, which is also idempotent.
* The command never deletes anything and never overwrites fields of rows
  that already exist.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from family.models import FamilyEvent, FamilyMember, FamilyStory, FamilyTree


def get_member(user, name, birth_date, **defaults):
    member, created = FamilyMember.objects.get_or_create(
        name=name, birth_date=birth_date, owner=user, defaults=defaults
    )
    return member, created


class Command(BaseCommand):
    help = "Load a small idempotent demonstration family for one user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Existing user who will own the sample records.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(
                "No such user: %r. Register the account first; this command "
                "never creates accounts." % options["username"]
            )
        FamilyTree.objects.get_or_create(owner=user)
        created = {"members": 0, "events": 0, "stories": 0}

        amara, made = get_member(
            user,
            "Amara Okafor",
            "1938-03-15",
            death_date="2012-11-02",
            birth_place="Enugu, Nigeria",
            bio="A village cook and storyteller who fed the whole street.",
        )
        created["members"] += made
        david, made = get_member(
            user,
            "David Okafor",
            "1935-06-20",
            death_date="2008-01-30",
            birth_place="Enugu, Nigeria",
            bio="A schoolteacher who loved music and chess.",
        )
        created["members"] += made
        grace, made = get_member(
            user,
            "Grace Okafor",
            "1964-05-01",
            birth_place="Enugu, Nigeria",
            lived_place="Toronto, Canada",
            relationship_label=FamilyMember.RELATIONSHIP_CHILD,
            related_to=amara,
            bio="A nurse who moved to Canada in 1989.",
        )
        created["members"] += made
        samuel, made = get_member(
            user,
            "Samuel Okafor",
            "1968-09-11",
            birth_place="Enugu, Nigeria",
            lived_place="Lagos, Nigeria",
            relationship_label=FamilyMember.RELATIONSHIP_CHILD,
            related_to=amara,
            bio="Runs a small bookshop in Lagos.",
        )
        created["members"] += made

        # Canonical links (add() never duplicates).
        amara.partners.add(david)
        grace.parents.add(amara, david)
        samuel.parents.add(amara, david)

        events = [
            (amara, 1938, "Amara Okafor is born in Enugu, Nigeria."),
            (None, 1960, "Nigeria gains independence."),
            (grace, 1964, "Grace Okafor is born."),
            (grace, 1989, "Grace moves to Toronto, Canada."),
        ]
        for member, year, text in events:
            _, made = FamilyEvent.objects.get_or_create(
                member=member, year=year, text=text, owner=user
            )
            created["events"] += made

        stories = [
            (
                amara,
                "Sunday jollof",
                "Grace",
                FamilyStory.CATEGORY_TRADITION,
                "Every Sunday Grandma Amara cooked jollof rice for the whole "
                "street. Nobody was ever turned away.",
            ),
            (
                samuel,
                "The long trip north",
                "Samuel",
                FamilyStory.CATEGORY_MEMORY,
                "The first time the family drove across the country, the car "
                "broke down three times before lunch.",
            ),
        ]
        for member, title, author, category, text in stories:
            _, made = FamilyStory.objects.get_or_create(
                member=member,
                title=title,
                owner=user,
                defaults={"author": author, "category": category, "text": text},
            )
            created["stories"] += made

        self.stdout.write(
            self.style.SUCCESS(
                "Sample family ready. Created this run: "
                "%(members)d member(s), %(events)d event(s), "
                "%(stories)d stor(ies)." % created
            )
        )
