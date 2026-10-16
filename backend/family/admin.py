from django.contrib import admin

from .models import (
    FamilyEvent,
    FamilyMember,
    FamilyStory,
    FamilyTree,
    RelativeConnection,
)


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "birth_date", "death_date", "birth_place", "updated_at")
    search_fields = ("name", "birth_place", "lived_place", "bio")
    list_filter = ("relationship_label",)
    filter_horizontal = ("parents", "partners")


@admin.register(FamilyEvent)
class FamilyEventAdmin(admin.ModelAdmin):
    list_display = ("year", "member", "text")
    list_filter = ("year",)
    search_fields = ("text",)


@admin.register(FamilyStory)
class FamilyStoryAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "category", "member")
    list_filter = ("category",)
    search_fields = ("title", "author", "text")


@admin.register(FamilyTree)
class FamilyTreeAdmin(admin.ModelAdmin):
    list_display = ("owner", "name", "center_member", "created_at")
    search_fields = ("owner__username", "name")


@admin.register(RelativeConnection)
class RelativeConnectionAdmin(admin.ModelAdmin):
    list_display = ("from_user", "to_user", "status", "updated_at")
    list_filter = ("status",)
