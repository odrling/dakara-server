#!/usr/bin/env python3
##
# Dakara Project
#
# Script for feeding the server database with songs from a directory
#

import os
import sys
import re
import logging
import importlib
import progressbar
import argparse
import subprocess
import json
from collections import defaultdict, OrderedDict
from pymediainfo import MediaInfo
from datetime import timedelta
from difflib import SequenceMatcher
from tempfile import TemporaryDirectory

import pysubs2
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import MultipleObjectsReturned

from library.models import *

# wrap a special stream for warnings
# the wrapping done by progressbar seems to reassign the ouput and flush it when
# needed, and not automatically
# if the standard error is wrapped, it mutes any exception, which is not
# acceptable
# so, we create a custom wrapped stream and assign warnings to use it
# since we cannot specify a new stream, we use stderr for that, and reassign
# it to its origineal value right after
origin_stderr = sys.stderr
wrapped_stderr = progressbar.streams.wrap_stderr()
sys.stderr = origin_stderr

# get logger
logger = logging.getLogger(__name__)

# hack the logger handler to use the wrapped stderr
if len(logger.handlers) > 0:
    logger.handlers[0].stream = wrapped_stderr


# get file system encoding
file_coding = sys.getfilesystemencoding()


class DatabaseFeeder:
    """ Class representing a list of DatabaseFeederEntry to feed the database
        with
    """

    def __init__(
            self,
            listing,
            dry_run=False,
            directory_kara="",
            directory="",
            progress_show=False,
            output_show=False,
            no_add_on_error=False,
            custom_parser=None,
            metadata_parser='ffprobe',
            stdout=sys.stdout,
            stderr=sys.stderr,
            tempdir="."
            ):
        """ Constructor

            Args
                listing (list): list of file names.
                dry_run (bool): flag for test mode (no save in database).
                directory_kara (str): base directory of the karaoke library.
                directory (str): directory of the songs to parse, relative to
                    `directory_kara`.
                progress_show (bool): show the progress bar.
                output_show (bool): show any output.
                no_add_on_error (bool): when true do not add song when parse
                    fails.
                custom_parser (module): name of a custom python module used to
                    extract data from file name; soo notes below.
                metadata_parser (str): name of the metadata parser to use
                    ('ffprobe', 'mediainfo' or `None`).
                stdout (file descriptor): standard output.
                stderr (file descriptor): standard error.
                tempdir (str): path to a temporary directory.

            About custom_parser:
                This module should define a method called `parse_file_name`
                which takes a file name as argument and return a dictionnary
                with the following:
                    title_music (str): title of the music.
                    detail (str): details about the music.
                    artists (list): of (str): list of artists.
                    title_work (str): name of the work related to this song.
                    subtitle_work (str): subname of the work related to this
                        song.
                    link_type (str): enum (OP ED IS IN) type of relation
                        between the work and the song.
                    link_nb (int): for OP and ED link type, number of OP or ED.

                All of these values, except `title_music`, are optional; if a
                    value is not used, set it to `None`.
        """
        if not isinstance(listing, (list, tuple)):
            raise ValueError("listing argument must be a list or a tuple")

        self.listing = listing
        self.dry_run = dry_run
        self.directory_kara = directory_kara
        self.directory = directory
        self.progress_show = progress_show
        self.output_show = output_show
        self.no_add_on_error = no_add_on_error
        self.custom_parser = custom_parser
        self.stdout = stdout
        self.stderr = stderr
        self.tempdir = tempdir
        self.metadata_parser = DatabaseFeeder.select_metadata_parser(metadata_parser)
        self.removed_songs = []

    def find_removed_songs(self, directory_listing):
        """ Find all songs in database which file has been removed
        """
        removed_songs = []
        for song in Song.objects.filter(directory=self.directory):
            if song.filename not in directory_listing:
                removed_songs.append(song)

        self.removed_songs = removed_songs

    def prune_removed_songs(self):
        """ Delete from database songs in removed_songs list
        """
        for song in self.removed_songs:
            song.delete()

    @staticmethod
    def select_metadata_parser(parser_name):
        """ Select the metadata parser class according to its name

            Args:
                parser_name (str): name of the parser.

            Returns:
                (:obj:`MetadataParser`) class of the parser.
        """
        if parser_name is None:
            return MetadataParser

        if parser_name == 'ffprobe':
            if not FFProbeMetadataParser.is_available():
                raise CommandError("ffprobe is not available")

            return FFProbeMetadataParser

        if parser_name == 'mediainfo':
            if not MediainfoMetadataParser.is_available():
                raise CommandError("mediainfo is not available")

            return MediainfoMetadataParser

        raise CommandError("Unknown metadata parser: '{}'".format(parser_name))

    @classmethod
    def from_directory(
            cls,
            *args,
            append_only=False,
            prune=False,
            **kwargs
            ):
        """ Overloaded constructor
            Extract files from directory

            Args:
                dry_run (bool): flag for test mode (no save in database).
                directory_kara (str): base directory of the karaoke library.
                directory (str): directory of the songs to parse, relative to
                    `directory_kara`.
                progress_show (bool): show the progress bar.
                no_add_on_error (bool): when true do not add song when parse
                    fails.
                custom_parser (module): name of a custom python module used to
                    extract data from file name; soo notes below.
                metadata_parser (str): name of the metadata parser to use
                    ('ffprobe', 'mediainfo' or `None`).
                stdout (file descriptor): standard output.
                stderr (file descriptor): standard error.
                append_only (bool): create only new songs, do not update
                    existing ones.
                prune (bool): remove databases entries not on disk.

            Returns:
                (:obj:`DatabaseFeeder`) feeder object.
        """
        # create instance of feeder with no feeder entries yet
        feeder = cls([], *args, **kwargs)

        # manage directory to scan
        directory_to_scan = os.path.join(feeder.directory_kara,
                feeder.directory)

        directory_to_scan_encoded = directory_to_scan.encode(file_coding)
        if not os.path.isdir(directory_to_scan_encoded):
            raise CommandError("Directory '{}' does not exist"\
                    .format(directory_to_scan))

        # list files in directory and split between media and subtitle
        directory_listing_media = []
        subtitle_by_filename = defaultdict(lambda: [], {})
        directory_listing_encoded = os.listdir(directory_to_scan_encoded)
        for filename_encoded in directory_listing_encoded:
            if not os.path.isfile(os.path.join(
                directory_to_scan_encoded,
                filename_encoded
                )):

                continue

            filename = filename_encoded.decode(file_coding)
            if not file_is_valid(filename):
                continue

            if file_is_subtitle(filename):
                name, extension = os.path.splitext(filename)
                subtitle_by_filename[name].append(extension)

            else:
                directory_listing_media.append(filename)


        feeder.find_removed_songs(directory_listing_media)

        # create progress bar
        text = "Collecting files"
        ProgressBar = feeder._get_progress_bar()
        bar = ProgressBar(max_value=len(directory_listing_media), text=text)

        # scan directory
        listing = []
        for filename in bar(directory_listing_media):
            entry = DatabaseFeederEntry(
                    filename,
                    feeder=feeder,
                    metadata_parser=feeder.metadata_parser,
                    associated_subtitles=subtitle_by_filename[
                        os.path.splitext(filename)[0]
                        ]
                    )

            # only add entry to feeder list if we are not in append only
            # mode, otherwise only if the entry is new in the database
            if entry.to_save or not append_only:
                listing.append(entry)

        # put listing in feeder
        feeder.listing = listing

        # Remove database entries whose file is no more
        if prune:
            feeder.prune_removed_songs()

        return feeder

    def _get_progress_bar(self, show=None):
        """ Get the progress bar class according to the verbosity requested

            Checks the `progress_show` attribute.

            Args:
                show (bool): if provided, bypass the `progress_show` attribute
                    in favour of this argument.

            Returns:
                Progress bar object.
        """
        if not self.output_show:
            return progressbar.NullBar

        if show is None:
            show = self.progress_show

        return TextProgressBar if show else TextNullBar


    def set_from_filename(self):
        """ Extract database fields from files name
        """
        # create progress bar
        text = "Extracting data from files name"
        ProgressBar = self._get_progress_bar()
        bar = ProgressBar(max_value=len(self.listing), text=text)

        # list of erroneous songs id
        error_ids = []

        for entry in bar(self.listing):
            try:
                entry.set_from_filename(self.custom_parser)

            except DatabaseFeederEntryError as error:
                # only show a warning in case of error
                logger.warning("Cannot parse file '{filename}': {error}"\
                        .format(
                            filename=entry.filename,
                            error=error
                            )
                        )

                error_ids.append(entry.song.id)

        # if no erroneous songs can be added, delete them from list
        if self.no_add_on_error:
            self.listing = [item for item in self.listing \
                    if item.song.id not in error_ids]

    def set_from_metadata(self):
        """ Extract database fields from files metadata
        """
        # create progress bar
        text = "Extracting data from files metadata"
        ProgressBar = self._get_progress_bar()
        bar = ProgressBar(max_value=len(self.listing), text=text)

        # extract metadata
        for entry in bar(self.listing):
            entry.set_from_metadata()

    def set_from_subtitle(self):
        """ Set song lyrics attribute by extracting it from subtitle if any
        """
        # create progress bar
        text = "Extracting lyrics from subtitle file"
        ProgressBar = self._get_progress_bar()
        bar = ProgressBar(max_value=len(self.listing), text=text)

        # extract lyrics
        for entry in bar(self.listing):
            entry.set_from_subtitle()

    def save(self):
        """ Save list in database

            Depending on the attribute `dry_run`, entries will be saved or
            just displayed on screen.
        """
        # create progress bar
        text = "Entries to save" if self.dry_run \
                else "Saving entries to database"

        # the progress bar is displayed only if requested and if we actually
        # save the songs (instead of displaying them)
        ProgressBar = self._get_progress_bar(
                self.progress_show and not self.dry_run
                )

        bar = ProgressBar(max_value=len(self.listing), text=text)

        # define action to perform depending on dry run mode or not
        if self.dry_run:
            def save(obj):
                obj.show(self.stdout)

        else:
            def save(obj):
                obj.save()

        # save entries
        for entry in bar(self.listing):
            save(entry)


class DatabaseFeederEntry:
    """ Class representing a song to upgrade or create in the database
    """

    def __init__(self, filename, feeder, associated_subtitles, metadata_parser=None):
        """ Constructor

            Detect if a song already exists in the database, then take it or
            create a new object not yet saved.

            Args:
                filename (str): name of the song file, serves as ID.
                directory (str): directory of the song file to store in the
                    database, serves as ID.
                metadata_parser (:obj:`MetadataParser`): metadata parser class.
                    Default is `MetadataParser`.
                associated_subtitles (list): contains a list of extentions for
                    each subtitle file with the same name in the same directory.
        """
        self.filename = filename
        self.directory = feeder.directory
        self.directory_kara = feeder.directory_kara
        self.removed_songs = feeder.removed_songs
        self.tempdir = feeder.tempdir
        self.associated_subtitles = associated_subtitles

        # if no metadata parser is provided, use the default one
        self.metadata_parser = metadata_parser or MetadataParser

        # get the song
        self.set_song()

    def set_song(self):
        """ Set song if it exists or create a new one

            Logic scheme:
                1. Song exists in database for the same filename and
                    directory;
                2. Song exists in database for the same filename and a
                    different directory;
                3. Song exists in database for a similar filename in the same
                    directory.
        """
        songs = Song.objects.filter(filename=self.filename, directory=self.directory)

        # several songs should not have the same filename and directory
        if len(songs) > 1:
            raise MultipleObjectsReturned

        # song exists with the same filename and directory
        if len(songs) == 1:
            self.song = songs.first()
            self.to_save = False

            return

        songs = Song.objects.filter(filename=self.filename)

        for song in songs:
            filepath = os.path.join(self.directory_kara,
                    song.directory, self.filename)

            # song exists with the same filename and a different directory
            # its previous location should be invalid
            if not os.path.isfile(filepath.encode(file_coding)):
                song.directory = self.directory
                self.song = song
                self.to_save = True

                return

        removed_song_matched = (None, 0, 0)
        for i, song in enumerate(self.removed_songs):
            ratio = is_similar(self.filename, song.filename)

            if ratio and ratio > removed_song_matched[1]:
                removed_song_matched = (song, ratio, i)

        # song exists in database for a similar filename in the same
        # directory
        if removed_song_matched[0] is not None:
            song.filename = self.filename
            self.song = song
            self.to_save = True

            self.removed_songs.pop(removed_song_matched[2])
            return

        # the song doesn't exist at all in the database
        self.song = Song(filename=self.filename, directory=self.directory)
        self.to_save = True

    def set_from_filename(self, custom_parser):
        """ Set attributes by extracting them from file name

            Args:
                custom_parser (module): module for custom parsing.
        """
        filename, _ = os.path.splitext(self.filename)

        # prepare fields
        self.song.title = filename
        self.title_work = None
        self.subtitle_work = None
        self.link_type = None
        self.link_nb = None
        self.artists = None
        self.work_type_query_name = None
        self.tags = None

        if custom_parser:
            try:
                data = custom_parser.parse_file_name(filename)

            except Exception as error:
                # re-raise the error with custom class and message
                raise DatabaseFeederEntryError(
                        "{klass}: {message}".format(
                            message=str(error),
                            klass=error.__class__.__name__
                            )

                        ) from error

            # fill fields
            self.song.title = data.get('title_music')
            self.song.version = data.get('version')
            self.song.detail = data.get('detail')
            self.song.detail_video = data.get('detail_video')
            self.title_work = data.get('title_work')
            self.subtitle_work = data.get('subtitle_work')
            self.work_type_query_name = data.get('work_type_query_name')
            self.link_type = data.get('link_type')
            self.link_nb = data.get('link_nb')
            self.episodes = data.get('episodes')
            self.artists = data.get('artists')
            self.tags = data.get('tags')

    def set_from_metadata(self):
        """ Set attributes by extracting them from metadata
        """
        file_path = os.path.join(self.directory_kara,
                self.directory, self.filename)

        metadata = self.metadata_parser.parse(file_path)
        self.song.duration = metadata.duration

    def set_from_subtitle(self):
        """ Set song lyrics attribute by extracting it from subtitle if any
        """
        for extension, Parser in PARSER_BY_EXTENSION.items():
            if extension in [e.lower() for e in self.associated_subtitles]:
                # obtain path to extensionless file
                file_name, _ = os.path.splitext(self.filename)
                file_path_base = os.path.join(self.directory_kara,
                        self.directory, file_name)

                # add extension
                file_path = file_path_base + extension

                lyrics = self.get_lyrics_from_file(file_path, Parser)
                if lyrics:
                    logger.debug("Extracted lyrics from '{}'".format(file_path))
                    self.song.lyrics = lyrics
                    return

        # here, we have tested all the subtitles extensions known, we searh a
        # subtitile in the video itself
        subtitle_file_path = os.path.join(self.tempdir, "subtitle.ass")
        if not FFmpegWrapper.is_available():
            return

        media_file_path = os.path.join(self.directory_kara, self.directory,
                self.filename)

        # try to get the lyrics
        try:
            if FFmpegWrapper.extract_subtitle(media_file_path, subtitle_file_path):
                lyrics = self.get_lyrics_from_file(subtitle_file_path,
                        PARSER_BY_EXTENSION['.ass'])

                if lyrics:
                    logger.debug(
                        "Extracted embedded lyrics from '{}'".format(
                            media_file_path
                            )
                        )

                    self.song.lyrics = lyrics
                    return

        finally:
            try:
                os.remove(subtitle_file_path)

            except OSError:
                pass

        logger.debug("No subtitle found for '{}'".format(
            media_file_path
            ))

    @staticmethod
    def get_lyrics_from_file(file_path, Parser):
        """ Parse the subtitle file to extract its lyrics

            Args:
                file_path (str): path to the subtitle file.
                Parser (object): parser to use.

            Returns:
                (str) lyrics, or `None` if the parser failed.
        """
        # try to parse the subtitle file and extract lyrics
        try:
            parser = Parser(file_path)
            return parser.get_lyrics()

            # If we extracted lyrics successfully,
            # We can stop now, no need to check other subtitles

        except Exception as error:
            logger.warning(
                "Invalid subtitle file '{filename}': {error}".format(
                    filename=os.path.basename(file_path),
                    error=error
                    )
                )

        return None


    def show(self, stdout=sys.stdout):
        """ Show the song content

            Args:
                stdout (file descriptor): standard output.
        """
        stdout.write('')

        # set key length to one quarter of terminal width or 20
        width, _ = progressbar.utils.get_terminal_size()
        length = max(int(width * 0.25), 20)

        # we cannot use the song serializer here because it will have troubles on
        # songs that are not already in the database
        # instead, we extract manually all the fields
        fields = {k: v for k, v in self.song.__dict__.items() \
                if k not in ('_state')}

        fields.update({k: v for k, v in self.__dict__.items() \
                if k not in ('filename', 'directory', 'directory_kara',
                    'song', 'metadata_parser', 'removed_songs')})

        for key, value in fields.items():
            stdout.write("{key:{length}s} {value}".format(
                key=key,
                value=repr(value),
                length=length
                ))

    def save(self):
        """ Save song in database.
        """
        self.song.save()

        # Create link to work if there is one
        if self.title_work:
            if self.work_type_query_name:
                work_type, created = WorkType.objects.get_or_create(
                        query_name=self.work_type_query_name
                        )

            else:
                work_type = None

            work, created = Work.objects.get_or_create(
                    title=self.title_work,
                    subtitle=self.subtitle_work,
                    work_type=work_type
                    )

            link, created_link = SongWorkLink.objects.get_or_create(
                    song_id=self.song.id,
                    work_id=work.id
                    )

            if self.link_type:
                link.link_type = self.link_type

            if self.link_nb:
                link.link_type_number = int(self.link_nb)

            else:
                link.link_type_number = None

            if self.episodes:
                link.episodes = self.episodes

            link.save()

        # Create tags to song if there are any
        if self.tags:
            for tag_name in self.tags:
                tag, created = SongTag.objects.get_or_create(name=tag_name)
                self.song.tags.add(tag)

        # Create link to artists if there are any
        if self.artists:
            for artist_name in self.artists:
                artist, created = Artist.objects.get_or_create(name=artist_name)
                self.song.artists.add(artist)


class DatabaseFeederEntryError(Exception):
    """ Class for handling errors raised when dealing with
        a file gathered by the feeder
    """


def file_is_valid(filename):
    """ Check the file validity

        A valid file is:
            Not a hidden file or blacklisted extension

        Args:
            filename (str): name of the file.

        Returns:
            (bool) true if the file is valid.
    """
    return all((
        # media file
        os.path.splitext(filename)[1] not in (
            '.db'
            ),

        # not hidden file
        filename[0] != ".",
        ))


def file_is_subtitle(filename):
    """ Check that the file is a subtitle

        Args:
            filename (str): name of the file.

        Returns:
            (bool) true if the file is a subtitle file.
    """
    return os.path.splitext(filename)[1] in list(PARSER_BY_EXTENSION.keys())


class TextProgressBar(progressbar.ProgressBar):
    """ Progress bar with text in the widgets
    """
    def __init__(self, *args, text=None, **kwargs):
        """ Constructor

            Args:
                text (str): text to display at the left of the line.
        """
        super(TextProgressBar, self).__init__(*args, **kwargs)

        # customize the widget if text is provided
        if text is not None:
            # space padded length for text
            # set length to one quarter of terminal width
            width, _ = progressbar.utils.get_terminal_size()
            length = int(width * 0.25)

            # truncate text if necessary
            if len(text) > length:
                half = int(length * 0.5)
                text = text[:half - 2].strip() + '...' + text[-half + 1:].strip()

            widgets = [
                    "{:{length}s} ".format(text, length=length)
                    ]

            widgets.extend(self.default_widgets())
            self.widgets = widgets


class TextNullBar(progressbar.NullBar):
    """ Muted bar wich displays one line of text instead
        with the amount of actions to process
    """
    def __init__(self, *args, max_value=None, text=None, **kwargs):
        """ Constructor

            Args:
                text (str): text to display.
        """
        super(TextNullBar, self).__init__(*args, **kwargs)
        self.text = text
        self.max_value = max_value

        if self.text:
            print("{} ({})".format(self.text, self.max_value))


class MetadataParser:
    """ Base class for metadata parser

        The class works as an interface for the various metadata parsers
        available.

        This class itself is a null parser that always returns a timedelta 0
        duration.
    """
    def __init__(self, metadata):
        self.metadata = metadata

    @staticmethod
    def is_available():
        """ Check if the parser is callable
        """
        return True

    @classmethod
    def parse(cls, filename):
        """ Parse metadata from file name

            Args:
                filename (str): path of the file to parse.
        """
        return cls(None)

    @property
    def duration(self):
        """ Get duration as timedelta object

            Returns timedelta 0 if unable to get duration.
        """
        return timedelta(0)


class MediainfoMetadataParser(MetadataParser):
    """ Metadata parser based on PyMediaInfo (wrapper for MediaInfo)

        The class works as an interface for the MediaInfo class, provided by the
        pymediainfo module.

        It does not seem to work on Windows, as the mediainfo DLL cannot be
        found.
    """
    @staticmethod
    def is_available():
        """ Check if the parser is callable
        """
        return MediaInfo.can_parse()

    @classmethod
    def parse(cls, filename):
        """ Parse metadata from file name

            Args:
                filename (str): path of the file to parse.
        """
        metadata = MediaInfo.parse(filename)
        return cls(metadata)

    @property
    def duration(self):
        """ Get duration as timedelta object

            Returns timedelta 0 if unable to get duration.
        """
        general_track = self.metadata.tracks[0]
        duration = getattr(general_track, 'duration', 0) or 0
        return timedelta(milliseconds=int(duration))


class FFProbeMetadataParser(MetadataParser):
    """ Metadata parser based on ffprobe

        The class works as a wrapper for the `ffprobe` command. The ffprobe3
        module does not work, so we do our own here.

        The command is invoked through `subprocess`, so it should work on
        Windows as long as ffmpeg is installed and callable from the command
        line. Data are passed as JSON string.

        Freely inspired from [this proposed
        wrapper](https://stackoverflow.com/a/36743499) and the [code of
        ffprobe3](https://github.com/DheerendraRathor/ffprobe3/blob/master/ffprobe3/ffprobe.py).
    """
    @staticmethod
    def is_available():
        """ Check if the parser is callable
        """
        try:
            with open(os.devnull, 'w') as tempf:
                subprocess.check_call(
                        ["ffprobe", "-h"],
                        stdout=tempf,
                        stderr=tempf
                        )

                return True

        except:
            return False

    @classmethod
    def parse(cls, filename):
        """ Parse metadata from file name

            Args:
                filename (str): path of the file to parse.
        """
        command = ["ffprobe",
                "-loglevel",  "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                filename
                ]

        pipe = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
                )

        out, err = pipe.communicate()
        return cls(json.loads(out.decode(sys.stdout.encoding)))

    @property
    def duration(self):
        """ Get duration as timedelta object

            Returns timedelta 0 if unable to get duration.
        """
        # try in generic location
        if 'format' in self.metadata:
            if 'duration' in self.metadata['format']:
                return timedelta(seconds=float(
                    self.metadata['format']['duration']
                    ))

        # try in the streams
        if 'streams' in self.metadata:
            # commonly stream 0 is the video
            for s in self.metadata['streams']:
                if 'duration' in s:
                    return timedelta(seconds=float(s['duration']))

        # if nothing is found
        return timedelta(0)


class FFmpegWrapper:
    """ Wrapper for FFmpeg
    """
    @staticmethod
    def is_available():
        """ Check if the parser is callable
        """
        try:
            with open(os.devnull, 'w') as tempf:
                subprocess.check_call(
                        ["ffmpeg", "-version"],
                        stdout=tempf,
                        stderr=tempf
                        )

                return True

        except:
            return False

    @staticmethod
    def extract_subtitle(input_file_path, output_file_path):
        """ Try to extract the first subtitle of the given input file into the
            output file given.

            Args:
                input_file_path (str): path to the input file.
                output_file_path (str): path to the requested output file.

            Returns:
                (bool) true if the extraction process is successful.
        """
        try:
            with open(os.devnull, 'w') as tempf:
                subprocess.check_call(
                        [
                            "ffmpeg",
                            "-i", input_file_path,
                            "-map", "0:s:0",
                            output_file_path
                            ],
                        stdout=tempf,
                        stderr=tempf
                        )

                return True

        except:
            return False


class SubtitleParser:
    """ Abstract class for subtitle parser
    """
    def __init__(self, filepath):
        pass

    def get_lyrics(self):
        return ""

class TXTSubtitleParser(SubtitleParser):
    """ Subtitle parser for txt files
    """
    def __init__(self, filepath):
        with open(filepath) as file:
            self.content = file.read()

    def get_lyrics(self):
        return self.content

class Pysubs2SubtitleParser(SubtitleParser):
    """ Subtitle parser for ass, ssa and srt files

        This parser extracts cleaned lyrics from the provided subtitle file.

        It uses the `pysubs2` package to parse the ASS file.

        Attributes:
            content (pysubs2 object): parsed subtitle.
            override_sequence (regex matcher): regex that matches any tag and
                any drawing area.
    """
    override_sequence = re.compile(
            r"""
                \{.*?\\p\d.*?\}     # look for drawing area start tag
                .*?                 # select draw instructions
                (?:                 # until...
                    \{.*?\\p0.*?\}  # draw area end tag
                    |
                    $               # or end of line
                )
                |
                \{.*?\}             # or simply select tags
            """,
            re.UNICODE | re.VERBOSE
            )

    def __init__(self, filepath):
        self.content = pysubs2.load(filepath)

    def get_lyrics(self):
        """ Gives the cleaned text of the Event block

            The text is cleaned in two ways:
                - All tags are removed;
                - Consecutive lines with the same content, the same start and
                      end time are merged. This prevents from getting "extra
                      effect lines" in the file.

            Returns:
                (str) Cleaned lyrics.
        """
        lyrics = []

        # previous line handles
        event_previous = None

        # loop over each dialog line
        for event in self.content:

            # Ignore comments
            if event.is_comment:
                continue

            # alter the cleaning regex
            event.OVERRIDE_SEQUENCE = self.override_sequence

            # clean the line
            line = event.plaintext.strip()

            # Ignore empty lines
            if not line:
                continue

            # append the cleaned line conditionnaly
            # Don't append if the line is a duplicate of previous line
            if not (event_previous and
                    event_previous.plaintext.strip() == line and
                    event_previous.start == event.start and
                    event_previous.end == event.end):

                lyrics.append(line)

            # update previous line handles
            event_previous = event

        return '\n'.join(lyrics)


PARSER_BY_EXTENSION = OrderedDict((
    ('.ass', Pysubs2SubtitleParser),
    ('.ssa', Pysubs2SubtitleParser),
    ('.srt', Pysubs2SubtitleParser),
    ('.txt', TXTSubtitleParser)
    ))


class Command(BaseCommand):
    """ Command available for `manage.py` for feeding the library database
    """
    help = "Import songs from directory."

    def add_arguments(self, parser):
        """ Extend arguments for the command
        """
        parser.add_argument(
                "directory-kara",
                help="Base directory of the karaoke library."
                )

        parser.add_argument(
                "--no-progress",
                help="Don't display progress bars.",
                action="store_true"
                )

        parser.add_argument(
                "--quiet",
                help="Do not display anything on run.",
                action="store_true"
                )

        parser.add_argument(
                "-r",
                "--dry-run",
                help="Run script in test mode, don't save anything in database.",
                action="store_true"
                )

        parser.add_argument(
                "-D",
                "--directory",
                help="Directory to scan, relative to 'directory-kara'.",
                default=""
                )

        parser.add_argument(
                "--parser",
                help="Name of a custom python module used to extract data from \
                file name; see internal doc for what is expected for this module.",
                default=None
                )

        parser.add_argument(
                "--metadata-parser",
                help="Which program to extract metadata from: \
                none (no parser), mediainfo or ffprobe (default).",
                default='ffprobe'
                )

        parser.add_argument(
                "--append-only",
                help="Create new songs, don't update existing ones.",
                action="store_true"
                )

        parser.add_argument(
                "--prune",
                help="Remove database entries for files no longer on disk.",
                action="store_true"
                )

        parser.add_argument(
                "--no-add-on-error",
                help="Do not add file when parse failed. \
                By default parse error still add the file unparsed.",
                action="store_true"
                )

        parser.add_argument(
                "--debug-sql",
                help="Show Django SQL logs (very verbose).",
                action="store_true"
                )

    def handle(self, *args, **options):
        """ Process the feeding
        """
        # directory-source
        # Normalize path to remove trailing slash
        directory_kara = os.path.normpath(options['directory-kara'])
        directory = options['directory']

        if directory:
            directory = os.path.normpath(directory)

        # debug SQL
        if options.get('debug_sql'):
            logger = logging.getLogger('django.db.backends')
            logger.setLevel(logging.DEBUG)
            logger.addHandler(logging.StreamHandler())

        # custom parser
        custom_parser = None
        if options.get('parser'):
            parser_directory = os.path.join(
                    os.getcwd(),
                    os.path.dirname(options['parser'])
                    )

            parser_name, _ = os.path.splitext(os.path.basename(options['parser']))
            sys.path.append(parser_directory)
            custom_parser = importlib.import_module(parser_name)

        # metadata parser
        metadata_parser = options.get('metadata_parser')
        if metadata_parser == 'none':
            metadata_parser = None

        with TemporaryDirectory(prefix="dakara.") as tempdir:
            # create feeder object
            database_feeder = DatabaseFeeder.from_directory(
                    directory_kara=directory_kara,
                    directory=directory,
                    dry_run=options.get('dry_run'),
                    append_only=options.get('append_only'),
                    prune=options.get('prune'),
                    progress_show=not options.get('no_progress'),
                    output_show=not options.get('quiet'),
                    custom_parser=custom_parser,
                    no_add_on_error=options.get('no_add_on_error'),
                    metadata_parser=metadata_parser,
                    stdout=self.stdout,
                    stderr=self.stderr,
                    tempdir=tempdir
                    )

            database_feeder.set_from_filename()
            database_feeder.set_from_metadata()
            database_feeder.set_from_subtitle()
            database_feeder.save()


def is_similar(string1, string2):
    """ Detect if string1 and strin2 are similar

        Returns:
            None if strings are not similar
            A float between 0 and 1 representing similarity, bigger is more similar.
    """
    THRESHOLD = 0.8
    ratio = SequenceMatcher(None, string1, string2).ratio()

    if ratio >= THRESHOLD:
        return ratio

    return None