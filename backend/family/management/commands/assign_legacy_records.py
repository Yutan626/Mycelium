"""Assign pre-ownership records to one account (explicit, one-time).

Usage (only after registering the account that should own them):

    python manage.py assign_legacy_records --username alice

Records created before ownership existed have ``owner=NULL`` and are
invisible to every account. This command stamps exactly those rows with
the given user. It never touches rows that already have an owner, never
deletes anything, and is safe to re-run (second run assigns zero rows).

Do NOT run this on a database where ownerless rows belong to different
people — split them manually first.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from family.models import FamilyEvent, FamilyMember, FamilyStory, FamilyTree


class Command(BaseCommand):
    help = "Assign ownerless legacy records to one existing user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            required=True,
            help="Existing user who will own the legacy records.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(
                "No such user: %r. Register the account first." % options["username"]
            )
        FamilyTree.objects.get_or_create(owner=user)
        counts = {
            "members": FamilyMember.objects.filter(owner__isnull=True).update(
                owner=user
            ),
            "events": FamilyEvent.objects.filter(owner__isnull=True).update(
                owner=user
            ),
            "stories": FamilyStory.objects.filter(owner__isnull=True).update(
                owner=user
            ),
        }
        self.stdout.write(
            self.style.SUCCESS(
                "Assigned to %s: %d member(s), %d event(s), %d stor(ies)."
                % (
                    user.username,
                    counts["members"],
                    counts["events"],
                    counts["stories"],
                )
            )
        )
