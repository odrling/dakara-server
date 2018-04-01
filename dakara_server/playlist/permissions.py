from django.core.exceptions import ObjectDoesNotExist
from rest_framework import permissions

from users.permissions import BasePermissionCustom
from .models import PlaylistEntry, Player, KaraStatus
from library.models import Song

class IsPlaylistManagerOrOwnerOrReadOnly(BasePermissionCustom):
    """ Handle permissions to modify playlist entries

        Permission scheme:
            Superuser can edit anything;
            Playlist manager can edit anything;
            Authenticated user can only edit their own data and display anything;
            Unauthenticated user cannot see anything.
    """
    def has_object_permission(self, request, view, obj):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # if the user is the superuser or the users manager, allow access
        if request.user.is_superuser:
            return True

        # for manager
        if request.user.has_playlist_permission_level('m'):
            return True

        # if the object belongs to the user
        return obj.owner == request.user


class IsPlaylistUserOrReadOnly(BasePermissionCustom):
    """ Handle permissions for creating playlist entries

        Permission scheme:
            Superuser can do anything;
            Playlist user can do anything;
            Authenticated can only display;
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # for modification
        return request.user.has_playlist_permission_level('u')


class IsPlaylistManagerOrReadOnly(BasePermissionCustom):
    """ Handle permissions for changing player status

        Permission scheme:
            Superuser can do anything;
            Playlist manager can do anything;
            Authenticated can only display;
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # for modification
        return request.user.has_playlist_permission_level('m')


class IsPlaylistManagerOrPlayingEntryOwnerOrReadOnly(BasePermissionCustom):
    """ Handle permissions for views related to playing entry

        Permission scheme:
            Superuser can edit anything;
            Playlist manager can edit anything;
            Authenticated user can only edit data if related to their own
                playing entry and display anything;
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        # for safe methods only
        if request.method in permissions.SAFE_METHODS:
            return True

        # if the user is the superuser or the users manager, allow access
        if request.user.is_superuser:
            return True

        # for manager
        if request.user.has_playlist_permission_level('m'):
            return True

        # if the currently playing song belongs to the user
        # Get player to get playing song
        player = Player.get_or_create()
        playlist_entry_id = player.playlist_entry_id
        playlist_entry = None
        if playlist_entry_id:
            playlist_entry = PlaylistEntry.objects.get(id=playlist_entry_id)

        if not playlist_entry:
            return False

        return playlist_entry.owner == request.user


class IsPlaylistAndLibraryManagerOrSongCanBeAdded(BasePermissionCustom):
    """ Handle permission for songs that can be added or not

        Permission scheme:
            Superuser can do anything;
            Managerof playlist and library can do anything;
            Playlist user can only access musics whose tags are not disabled.
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        # for manager of playlist and library
        if request.user.has_playlist_permission_level('m') and \
                request.user.has_library_permission_level('m'):
            return True

        # get song
        song_id = request.data.get('song')
        if not song_id:
            return True

        # check the song has no disabled tags
        try:
            song = Song.objects.get(pk=song_id)
            return not any([t.disabled for t in song.tags.all()])

        except ObjectDoesNotExist:
            return True


class IsPlayer(BasePermissionCustom):
    """ Handle permissions player management

        Permission scheme:
            Superuser can do anything;
            Player can do anything;
            Authenticated cannot do anything;
            Unauthenticated user cannot see anything.
    """
    def has_permission_custom(self, request, view):
        return request.user.has_playlist_permission_level('p')


class KaraStatusIsNotStoppedOrReadOnly(permissions.BasePermission):
    """ Grant access to not safe views if the kara is not in stop mode
    """
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        kara_status = KaraStatus.get_object()
        return kara_status.status != KaraStatus.STOP
