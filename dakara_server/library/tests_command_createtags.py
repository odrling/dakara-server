from tempfile import NamedTemporaryFile
from django.core.management import call_command
from django.test import TestCase
from .models import SongTag

class CreatetagsCommandTestCase(TestCase):

    def test_createtags_command(self):
        """
        Test create tags command
        """
        # Pre-Assertions
        tags = SongTag.objects.order_by('name')
        self.assertEqual(len(tags), 0)

        file_content = """tags:
  - name: TAGNAME1
    color_id: 0
  - name: TAGNAME2
    color_id: 5"""

        # Create temporary config file
        with NamedTemporaryFile(mode='wt') as config_file:
            config_file.write(file_content)
            config_file.flush()

            # Call command
            args = [config_file.name]
            opts = {'quiet': True}
            call_command('createtags', *args, **opts)

            # Post-Assertions
            tags = SongTag.objects.order_by('name')
            self.assertEqual(len(tags), 2)
            self.assertEqual(tags[0].name, "TAGNAME1")
            self.assertEqual(tags[0].color_id, 0)
            self.assertEqual(tags[1].name, "TAGNAME2")
            self.assertEqual(tags[1].color_id, 5)

    def test_createtags_command_prune(self):
        """
        Test create tags command with existing tags and prune option
        """

        # Create existing tags
        # This tag exists in config file
        # its color id will be updated by the command
        tag1 = SongTag()
        tag1.name= "TAGNAME1"
        tag1.save()

        # This is not in config file
        # Will be removed
        tag2 = SongTag()
        tag2.name = "TAGOLD"
        tag2.save()

        # Pre-Assertions
        tags = SongTag.objects.order_by('name')
        self.assertEqual(len(tags), 2)
        self.assertEqual(tags[0].name, "TAGNAME1")
        self.assertEqual(tags[0].color_id, None)
        self.assertEqual(tags[1].name, "TAGOLD")

        file_content = """tags:
  - name: TAGNAME1
    color_id: 0
  - name: TAGNAME2
    color_id: 5"""

        # Create temporary config file
        with NamedTemporaryFile(mode='wt') as config_file:
            config_file.write(file_content)
            config_file.flush()

            # Call command
            args = [config_file.name]
            opts = {'quiet': True, 'prune': True}
            call_command('createtags', *args, **opts)

            # Post-Assertions
            tags = SongTag.objects.order_by('name')
            # Only the two tags from config file
            self.assertEqual(len(tags), 2)
            # Tag 1 has updated color id but same id
            self.assertEqual(tags[0].name, "TAGNAME1")
            self.assertEqual(tags[0].id, tag1.id)
            self.assertEqual(tags[0].color_id, 0)
            # Tag 2 was created
            self.assertEqual(tags[1].name, "TAGNAME2")
            self.assertEqual(tags[1].color_id, 5)