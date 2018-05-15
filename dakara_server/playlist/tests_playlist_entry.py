from unittest.mock import patch
from datetime import datetime, timedelta

from django.core.urlresolvers import reverse
from django.utils.dateparse import parse_datetime
from rest_framework import status

from .base_test import BaseAPITestCase, tz
from .models import PlaylistEntry, Player


class PlaylistEntryListViewListCreateAPIViewTestCase(BaseAPITestCase):
    url = reverse('playlist-entries-list')

    def setUp(self):
        self.create_test_data()

    @patch('playlist.views.datetime',
           side_effect=lambda *args, **kwargs: datetime(*args, **kwargs))
    def test_get_playlist_entries_list(self, mocked_datetime):
        """Test to verify playlist entries list
        """
        # patch the now method
        now = datetime.now(tz)
        mocked_datetime.now.return_value = now

        # Login as simple user
        self.authenticate(self.user)

        # Get playlist entries list
        # Should only return entries with `was_played`=False
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 2)

        # Playlist entries are in order of creation
        pe1 = response.data['results'][0]
        pe2 = response.data['results'][1]
        self.check_playlist_entry_json(pe1, self.pe1)
        self.check_playlist_entry_json(pe2, self.pe2)

        # check the date of the end of the playlist
        self.assertEqual(parse_datetime(response.data['date_end']),
                         now + self.pe1.song.duration + self.pe2.song.duration)

        # check the date of play of each entries
        self.assertEqual(parse_datetime(pe1['date_play']), now)
        self.assertEqual(parse_datetime(pe2['date_play']),
                         now + self.pe1.song.duration)

    @patch('playlist.views.datetime',
           side_effect=lambda *args, **kwargs: datetime(*args, **kwargs))
    def test_get_playlist_entries_list_while_playing(self, mocked_datetime):
        """Test to verify playlist entries play dates while playing

        The player is currently in the middle of the song, play dates should
        take account of the remaining time of the player.
        """
        # patch the now method
        now = datetime.now(tz)
        mocked_datetime.now.return_value = now

        # set the player
        player = Player.get_or_create()
        player.playlist_entry_id = self.pe1.id
        play_duration = timedelta(seconds=2)
        player.timing = play_duration
        player.save()

        # Login as simple user
        self.authenticate(self.user)

        # Get playlist entries list
        # Should only return entries with `was_played`=False
        response = self.client.get(self.url)

        # Get playlist entries list
        # Should only return entries with `was_played`=False
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        # Playlist entries are in order of creation
        pe2 = response.data['results'][0]
        self.check_playlist_entry_json(pe2, self.pe2)

        # check the date of play
        self.assertEqual(parse_datetime(response.data['date_end']),
                         now + self.pe1.song.duration - play_duration +
                         self.pe2.song.duration)

        # check the date of play of each entries
        self.assertEqual(parse_datetime(pe2['date_play']),
                         now + self.pe1.song.duration - play_duration)

    def test_get_playlist_entries_list_forbidden(self):
        """Test to verify playlist entries list forbidden when not logged in
        """
        # Get playlist entries list
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_create_playlist_entry(self):
        """Test to verify playlist entry creation
        """
        # Login as playlist user
        self.authenticate(self.p_user)

        # Pre assert 4 entries in database
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Post new playlist entry
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check playlist entry has been created in database
        self.assertEqual(PlaylistEntry.objects.count(), 5)
        new_entry = PlaylistEntry.objects.order_by('-date_created')[0]
        # Entry was created with for song1
        self.assertEqual(new_entry.song.id, self.song1.id)
        # Entry's owner is the user who created it
        self.assertEqual(new_entry.owner.id, self.p_user.id)

    def test_post_create_playlist_entry_kara_status_stop_forbidden(self):
        """Test to verify playlist entry cannot be created when kara is stopped
        """
        # stop kara
        self.set_kara_status_stop()

        # Login as playlist user
        self.authenticate(self.manager)

        # Post new playlist entry
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('playlist.views.settings')
    def test_post_create_playlist_entry_playlist_full_forbidden(
            self, mock_settings):
        """Test to verify playlist entry creation
        """
        # mock the settings
        mock_settings.PLAYLIST_SIZE_LIMIT = 1

        # Login as playlist user
        self.authenticate(self.p_user)

        # Pre assert 4 entries in database
        # (2 in queue)
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Post new playlist entry
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_create_user_forbidden(self):
        """Test to verify simple user cannot create playlist entries
        """
        # Login as simple user
        self.authenticate(self.user)

        # Attempt to post new playlist entry
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_playlist_entries_list_playing_entry(self):
        """Test to verify playlist entries list does not include playing song
        """
        # Simulate a player playing next song
        self.player_play_next_song()

        # Login as simple user
        self.authenticate(self.user)

        # Get playlist entries list
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)

        # Playlist entries are in order of creation
        self.check_playlist_entry_json(response.data['results'][0], self.pe2)

    def test_post_create_playlist_entry_disabled_tag(self):
        """Test playlist entry creation for a song with a disabled tag

        The creation is forbidden.
        """
        # Login as playlist user
        self.authenticate(self.p_user)

        # Set tag1 disabled
        self.tag1.disabled = True
        self.tag1.save()

        # Post new playlist entry with disabled Tag 1
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_create_playlist_entry_disabled_tag_manager(self):
        """Test playlist entry for song with a disabled tag if manager

        The user is manager for playlist and library, the creation is allowed.
        """
        # Login as playlist user
        user = self.create_user('manager',
                                playlist_level='m',
                                library_level='m')
        self.authenticate(user)

        # Set tag1 disabled
        self.tag1.disabled = True
        self.tag1.save()

        # Post new playlist entry with disabled Tag 1
        response = self.client.post(self.url, {"song_id": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class PlaylistEntryViewDestroyAPIViewTestCase(BaseAPITestCase):

    def setUp(self):
        self.create_test_data()

        # Create urls to access these playlist entries
        self.url_pe1 = reverse(
            'playlist-entries-detail',
            kwargs={
                "pk": self.pe1.id})
        self.url_pe2 = reverse(
            'playlist-entries-detail',
            kwargs={
                "pk": self.pe2.id})
        self.url_pe3 = reverse(
            'playlist-entries-detail',
            kwargs={
                "pk": self.pe3.id})

    def test_delete_playlist_entry_manager(self):
        """Test to verify playlist entry deletion as playlist manager
        """
        # Login as playlist manager
        self.authenticate(self.manager)

        # Pre assert 4 entries in database
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Delete playlist entries created by manager
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 3)
        entries = PlaylistEntry.objects.filter(id=self.pe1.id)
        self.assertEqual(len(entries), 0)

        # Delete playlist entries created by other user
        response = self.client.delete(self.url_pe2)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 2)

    def test_delete_playlist_entry_playlist_user(self):
        """Test to verify playlist entry deletion as playlist user
        """
        # Login as playlist user
        self.authenticate(self.p_user)

        # Pre assert 4 entries in database
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Delete playlist entries created by self
        response = self.client.delete(self.url_pe2)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 3)
        entries = PlaylistEntry.objects.filter(id=self.pe2.id)
        self.assertEqual(len(entries), 0)

        # Attempt to delete playlist entry created by other user
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_playlist_entry_playing(self):
        """Test to verify playing entry can not be deleted
        """
        # Simulate a player playing next song
        self.player_play_next_song()

        # Login as playlist manager
        self.authenticate(self.manager)

        # Pre assert 4 entries in database
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Attempt to delete playing entry
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # This playlist entry is still there
        self.assertEqual(PlaylistEntry.objects.count(), 4)
        entries = PlaylistEntry.objects.filter(id=self.pe1.id)
        self.assertEqual(len(entries), 1)

    def test_delete_playlist_entry_played(self):
        """Test to verify already played entry can not be deleted
        """
        # Login as playlist manager
        self.authenticate(self.manager)

        # Pre assert 4 entries in database
        self.assertEqual(PlaylistEntry.objects.count(), 4)

        # Attempt to delete already played entry
        response = self.client.delete(self.url_pe3)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # This playlist entry is still there
        self.assertEqual(PlaylistEntry.objects.count(), 4)
        entries = PlaylistEntry.objects.filter(id=self.pe3.id)
        self.assertEqual(len(entries), 1)
