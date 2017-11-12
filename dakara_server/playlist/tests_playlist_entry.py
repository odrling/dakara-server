from django.core.urlresolvers import reverse
from rest_framework import status
from .base_test import BaseAPITestCase
from .models import PlaylistEntry

class PlaylistEntryListCreateAPIViewTestCase(BaseAPITestCase):
    url = reverse('playlist-list')

    def setUp(self):
        self.create_test_data()

    def test_get_playlist_entries_list(self):
        """
        Test to verify playlist entries list
        """
        # Login as simple user 
        self.authenticate(self.user)

        # Get playlist entries list 
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)
        self.assertEqual(len(response.data['results']), 2)

        # Playlist entries are in order of creation
        self.check_playlist_entry_json(response.data['results'][0], self.pe1)
        self.check_playlist_entry_json(response.data['results'][1], self.pe2)

    def test_get_playlist_entries_list_forbidden(self):
        """
        Test to verify playlist entries list is not available when not logged in
        """
        # Get playlist entries list
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_create_playlist_entry(self):
        """
        Test to verify playlist entry creation
        """
        # Login as playlist user
        self.authenticate(self.p_user)

        # Post new playlist entry
        response = self.client.post(self.url, {"song": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Check playlist entry has been created in database
        self.assertEqual(PlaylistEntry.objects.count(), 3)
        new_entry = PlaylistEntry.objects.order_by('-date_created')[0]
        # Entry was created with for song1
        self.assertEqual(new_entry.song.id, self.song1.id)
        # Entry's owner is the user who created it
        self.assertEqual(new_entry.owner.id, self.p_user.id)

    def test_post_create_user_forbidden(self):
        """
        Test to verify simple user cannot create playlist entries
        """
        # Login as simple user 
        self.authenticate(self.user)

        # Attempt to post new playlist entry
        response = self.client.post(self.url, {"song": self.song1.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_playlist_entries_list_playing_entry(self):
        """
        Test to verify playlist entries list does not include playing song
        """
        # Simulate a player playing next song
        self.player_play_next_song()

        # Login as simple user 
        self.authenticate(self.user)

        # Get playlist entries list 
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)

        # Playlist entries are in order of creation
        self.check_playlist_entry_json(response.data['results'][0], self.pe2)

class PlaylistEntryRetrieveUpdateDestroyAPIViewTestCase(BaseAPITestCase):

    def setUp(self):
        self.create_test_data()

        # Create urls to access these playlist entries
        self.url_pe1 = reverse('playlist-detail', kwargs={"pk": self.pe1.id})
        self.url_pe2 = reverse('playlist-detail', kwargs={"pk": self.pe2.id})


    def test_delete_playlist_entry_manager(self):
        """
        Test to verify playlist entry deletion as playlist manager
        """
        # Login as playlist manager
        self.authenticate(self.manager)

        # Delete playlist entries created by manager
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 1)
        entries = PlaylistEntry.objects.filter(id=self.pe1.id)
        self.assertEqual(len(entries), 0)

        # Delete playlist entries created by other user
        response = self.client.delete(self.url_pe2)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 0)

    def test_delete_playlist_entry_playlist_user(self):
        """
        Test to verify playlist entry deletion as playlist user
        """
        # Login as playlist user
        self.authenticate(self.p_user)

        # Delete playlist entries created by self
        response = self.client.delete(self.url_pe2)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # This playlist entry has been removed from database
        self.assertEqual(PlaylistEntry.objects.count(), 1)
        entries = PlaylistEntry.objects.filter(id=self.pe2.id)
        self.assertEqual(len(entries), 0)

        # Attempt to delete playlist entry created by other user
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_playlist_entry_playing(self):
        """
        Test to verify playing entry can not be deleted
        """
        # Simulate a player playing next song
        self.player_play_next_song()

        # Login as playlist manager
        self.authenticate(self.manager)

        # Attempt to delete playing entry 
        response = self.client.delete(self.url_pe1)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # This playlist entry is still there
        self.assertEqual(PlaylistEntry.objects.count(), 2)
        entries = PlaylistEntry.objects.filter(id=self.pe1.id)
        self.assertEqual(len(entries), 1)