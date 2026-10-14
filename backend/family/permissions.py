"""Object-level permissions for private family data."""

from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Allow access only to records owned by the requesting user.

    Querysets are also filtered by owner, so cross-account detail lookups
    normally 404 before reaching this check. This is defense in depth for
    update/delete paths.
    """

    message = "You do not have access to this record."

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "owner", None)
        return owner is not None and owner == request.user


class IsConnectionParty(permissions.BasePermission):
    """Allow access only to users on either side of a connection thread."""

    message = "You are not part of this connection."

    def has_object_permission(self, request, view, obj):
        return obj.from_user == request.user or obj.to_user == request.user
