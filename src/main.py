'''
Usage:
    remix.audio_dl.py <URL> [--debug | --error]
    [-I <INTERVAL>][-A][-AP | --no-playlist-folder][-alr][--original-metadata]
    [--download-archive <file>][--path <path>]
    [--flac | --flac16 | --flacmin | --onlymp3]


    remix.audio_dl.py -h | --help
    remix.audio_dl.py --version
Options:
    -h --help                       Show this screen.
    --version                       Show version.

    -I <INTERVAL>                   Download songs within the interval, including bounds.
                                    Indexing starts at 1.
                                    Format: leftbound-rightbound (example: 10-31).
                                    Accepts left- and right-unbounded intervals (example: 7- or -25).
                                    Does not work with single song URls.

    -A                              Add artist prefix to filename.
    -AP                             Add artist prefix to playlist folder.
    -alr                            Skip already downloaded files with the same file name.
    --original-metadata             Do not add/overwrite new metadata.
    --download-archive <file>       Keep track of track IDs in an archive file,
                                    and skip already-downloaded IDs.
    --no-playlist-folder            Download playlist tracks into main directory,
                                    instead of making a playlist subfolder.
    --path <path>                   Custom download path.
    --flac                          Convert WAV, AIFF, and ALAC files to FLAC.
                                    Requires ffmpeg binary on path.
    --flac16                        Same as --flac but also downscales 32bit and 24bit filed to 16bit.
    --flacmin                       Same as --flac16 but also downsamples any samplerate above 48kHz down to 44.1kHz or 48kHz.
    --onlymp3                       Convert all downloaded files to MP3 if not already MP3.
                                    Requires ffmpeg binary on path.
'''
import logging
import os
import re
import sys
import urllib
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from docopt import docopt
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, COMM
from mutagen.mp3 import MP3

__version__ = '0.1'
ARGUMENTS: dict

DOWNLOAD_CACHE_FILE_PATH = 'rx-dl.cache'
COVER_FILE_NAME = '_cover.jpg'
AUDIO_FILE_NAME_PREFIX = '.\\'

logger = logging.getLogger(__name__)


def main():
    init()

    url = ARGUMENTS['<URL>']
    if not validate_url(url):
        sys.exit(1)

    download_playlist(url)


    url_case = url_type(url)

    if url_case == 'single':
        download_single_url(url)
    elif url_case == 'playlist':
        download_playlist(url)

    post_process()
    sys.exit(0)


def validate_url(url: str) -> bool:
    return (
            url.startswith('https://remix.audio/track/')
            or url.startswith('https://remix.audio/explore/')
            or (url.startswith('https://remix.audio/profile/') and (
            not url.endswith('/subscriptions') or url.endswith('/subscribers')))
            or url.startswith('https://remix.audio/search/filter/tracks/')
            or url.startswith('https://remix.audio/playlist/')
    )


def url_type(url: str) -> str:
    pass


def download_url(url: str):
    download_playlist(url)


def download_single_url(url: str, track_number: int = -1, album: str = None):
    x = requests.get(url)
    text = x.text
    soup = BeautifulSoup(text, 'html.parser')

    # upload date
    # song id
    upload_date_div = soup.find('div', {'class': 'timeago'})
    # 2025-02-03T10:23:47+00:00 -> 2025-02-03
    upload_date = upload_date_div.get('title')[:10]
    song_id = upload_date_div.parent.get('id').removeprefix('time')

    # title
    song_name = soup.find('div', {'id': f'song-name{song_id}'}).text

    # uploader
    uploader = soup.find('a', {'id': f'song-author{song_id}'}).text

    # file url
    # file name
    play_button_div = soup.find('div', {'id': f'play{song_id}'})
    audio_file_url = play_button_div.get('data-track-url')
    audio_file_name_with_extension = play_button_div.get('data-track-name')
    file_path = Path(audio_file_name_with_extension)

    audio_file_name = file_path.stem
    audio_file_type = file_path.suffix.lower()

    audio_file_name_with_extension = f'{AUDIO_FILE_NAME_PREFIX}{to_file_path_safe_string(song_name)} [{song_id}]{audio_file_type}'
    logger.info(f'Downloading {audio_file_name_with_extension}')
    urllib.request.urlretrieve(audio_file_url, DOWNLOAD_CACHE_FILE_PATH, show_progress)

    # cover
    # 25x,50x,75x,100x,112x,200x,300x,500x
    song_art_url = soup.find('img', {'id': f'song-art{song_id}'}).get('src').replace('/112/112/', '/500/500/')
    logger.debug(f'Downloading cover art: {song_art_url}')
    urllib.request.urlretrieve(song_art_url, COVER_FILE_NAME)

    # genres
    genres = set(
        [genre.text.removeprefix('#') for genre in
         soup.find('div', {'class': 'haus-tag-container'}).find_all('a')]
    )
    genres -= set(['original', 'remix'])
    genres = ', '.join(genres)

    # description
    # (licence)
    # publisher
    # relase date
    song_details_div = soup.find('div', {'class': 'track-description-container'})
    song_details = song_details_div.find_all('div', {'class': 'sidebar-description'})
    for song_detail in song_details:
        publisher_or_date = song_detail.find('strong')

        # case: description or licence
        if publisher_or_date is None:
            description_or_licence = song_detail.find('div', {'class': 'sidebar-license'})

            # case: description
            if description_or_licence is None:
                song_description = song_detail.text

            # case: licence
            else:
                pass

        # case: publisher
        elif 'Record label' in song_detail.text:
            publisher = publisher_or_date.text

        # case: release date
        # specified release date has higher priority than upload date
        elif 'Release date' in song_detail.text:
            release_date = publisher_or_date.text
            # February 03, 2025 -> 2025-02-03
            d = datetime.strptime(release_date, '%B %d, %Y')
            upload_date = d.strftime('%Y-%m-%d')

    # apply tags
    if (audio_file_type == '.mp3'):

        audio = MP3(DOWNLOAD_CACHE_FILE_PATH, ID3=ID3)

        # create ID3 Tag header if empty
        if audio.tags is None:
            audio.tags = ID3()

        # remove already embedded cover(s)
        # remove existing comment(s)
        cover_and_comment_keys = [key for key in audio.keys() if ('APIC' in key or 'COMM' in key)]
        for key in cover_and_comment_keys:
            del audio.tags[key]

        # create and set comment field
        try:
            audio.tags['COMM::eng'] = COMM()
            audio.tags['COMM::eng'].text = [song_description]
        except Exception as e:
            logger.debug(e)

        # set cover
        audio.tags.add(
            APIC(
                encoding=0,  # 3 is for utf-8
                mime='image/jpeg',  # image/jpeg or image/png
                type=3,  # 3 is for the cover image
                desc=u'Cover',
                data=open(COVER_FILE_NAME, 'rb').read()
            )
        )
        audio.save()

        audio = EasyID3(DOWNLOAD_CACHE_FILE_PATH)
        # print(audio.keys())
        # print(audio.pprint())
        audio['title'] = song_name
        audio['artist'] = uploader
        audio['date'] = upload_date
        audio['website'] = url
        audio['genre'] = genres

        if album is not None:
            audio['album'] = album

        if track_number > 0:
            audio['tracknumber'] = str(track_number)

        try:
            audio['copyright'] = publisher
            audio['organization'] = publisher
        except Exception as e:
            logger.debug(e)

        audio.save()

    os.rename(DOWNLOAD_CACHE_FILE_PATH, audio_file_name_with_extension)

    delete_cover_file()


def download_playlist(url: str):
    global AUDIO_FILE_NAME_PREFIX
    x = requests.get(url)
    text = x.text
    soup = BeautifulSoup(text, 'html.parser')

    playlist_title_div = soup.find('div', {'class': 'playlist-title'})
    playlist_title = playlist_title_div.text
    # safe playlist title for folder name
    safe_playlist_title = to_file_path_safe_string(playlist_title)

    os.makedirs(safe_playlist_title, exist_ok=True)
    AUDIO_FILE_NAME_PREFIX = f'.\\{safe_playlist_title}\\'

    songs_divs = soup.find_all('div', {'class': 'song-container'})
    song_ids = [song.get('id').removeprefix('track') for song in songs_divs]

    for count, song_id in enumerate(song_ids, start=1):
        # if count <= 6:
        #     continue
        download_single_url(f'https://remix.audio/track/{song_id}', track_number=count, album=playlist_title)


def show_progress(block_num, block_size, total_size):
    print(f'{round(block_num * block_size / total_size * 100, 2)}%', end='\r')


def init():
    global ARGUMENTS
    ARGUMENTS = docopt(__doc__, version=__version__)
    delete_cover_file()

    if ARGUMENTS['--debug']:
        logger.setLevel(logging.DEBUG)
    elif ARGUMENTS['--error']:
        logger.setLevel(logging.ERROR)
    else:
        logger.setLevel(logging.INFO)


def post_process():
    delete_cover_file()
    delete_cache()


def delete_cover_file():
    if os.path.isfile(COVER_FILE_NAME):
        os.unlink(COVER_FILE_NAME)


def delete_cache():
    if os.path.isfile(DOWNLOAD_CACHE_FILE_PATH):
        os.unlink(DOWNLOAD_CACHE_FILE_PATH)


def to_file_path_safe_string(unsafe_string: str) -> str:
    return re.sub(r"[/\\?%*:|\"<>\x7F\x00-\x1F]", "_", unsafe_string)


def rectify_bounds(start_index, end_index, iterable_size) -> tuple:
    pass


if __name__ == '__main__':
    # wav playlist https://remix.audio/playlist/2859
    # print(EasyID3.valid_keys.keys())
    main()
