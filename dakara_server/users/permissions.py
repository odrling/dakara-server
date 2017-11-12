from rest_framework import permissions

class BasePermissionCustom(permissions.BasePermission):
    """ Base permission class for the project, check the basic permissions

        Permission scheme:
            Superuser can do anything;
            Unauthenticated user cannot do anything.

        The permission methods call a custom method for specific permissions.
    """

    def has_permission(self, request, view):

        # if the user is not authenticated, deny access
        if not request.user or not request.user.is_authenticated():
            return False

        # if the user is the superuser or the users manager, allow access
        if request.user.is_superuser:
            return True

        # call specific permission check
        return self.has_permission_custom(request, view)

    def has_permission_custom(self, request, view):
        """ Stub for specific permissions check
        """
        return True


class IsUsersManagerOrReadOnly(BasePermissionCustom):
    """ Handle permissions for the User app

        Permission scheme:
            Superuser can edit anything;
            Users Manager can edit anything;
            Authenticated user can only display data;
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        # for manager
        if request.user.has_users_permission_level('m'):
            return True

        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True


class IsUsersManagerOrSelfOrReadOnly(BasePermissionCustom):
    """ Handle permissions for the User app

        Permission scheme:
            Superuser can edit anything;
            Users Manager can edit anything;
            Authenticated user can edit self;
            Unauthenticated user cannot see anything.
    """
    def has_object_permission(self, request, view, obj):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # if the user is the superuser, allow access
        if request.user.is_superuser:
            return True

        # for manager
        if request.user.has_users_permission_level('m'):
            return True

        # if the object belongs to the user
        return obj == request.user


class IsSelf(BasePermissionCustom):
    """ Handle permissions for the User app

        Permission scheme:
            Superuser can edit anything;
            Authenticated user can only edit self;
            Unauthenticated user cannot see anything.
    """
    def has_object_permission(self, request, view, obj):
        # if the object belongs to the user
        return obj == request.user


class IsNotSelfOrReadOnly(BasePermissionCustom):
    """ Handle permissions for the User app

        Permission scheme:
            Superuser can edit anything;
            Authenticated user cannot edit self;
            Unauthenticated user cannot see anything.
    """
    def has_object_permission(self, request, view, obj):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # if the user is the superuser, allow access
        if request.user.is_superuser:
            return True

        # if the object belongs to someone else
        return obj != request.user