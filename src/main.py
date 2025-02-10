'''
Usage:
    remix.audio_dl.py <URL> [--debug | --error]
    remix.audio_dl.py -h | --help
Options:
    -h --help     Show this screen.
'''
import logging
import os
import re
import sys
import urllib
from datetime import datetime
from pathlib import Path

import requests
import mutagen
from docopt import docopt
from bs4 import BeautifulSoup
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, COMM
from mutagen.mp3 import MP3

COVER_FILE_NAME = '_cover.jpg'
AUDIO_FILE_NAME_PREFIX = '.\\'

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def main():
    init()
    arguments = docopt(__doc__)

    if arguments['--debug']:
        logger.level = logging.DEBUG
    elif arguments['--error']:
        logger.level = logging.ERROR

    url = arguments['<URL>']
    if not validate_url(url):
        sys.exit(1)

    download_url(url)
    sys.exit(0)


def validate_url(url: str) -> bool:
    if (
            url.startswith('https://remix.audio/track/')
            or url.startswith('https://remix.audio/explore/')
            or (url.startswith('https://remix.audio/profile/') and (
            not url.endswith('/subscriptions') or url.endswith('/subscribers')))
            or url.startswith('https://remix.audio/search/filter/tracks/')
            or url.startswith('https://remix.audio/playlist/')
    ):
        return True
    return True


def url_type(url: str) -> str:
    pass


def download_url(url: str):
    download_playlist(url)


def download_single_url(url: str, track_number: int = -1):
    x = requests.get(url)
    text = x.text
    # print(text)
    soup = BeautifulSoup(text, 'html.parser')

    # upload date
    # song id
    upload_date_div = soup.find('div', {'class': 'timeago'})
    # 2025-02-03T10:23:47+00:00 -> 2025-02-03
    upload_date = upload_date_div.get('title')[:10]
    song_id = upload_date_div.parent.get('id').replace('time', '')

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
    print(audio_file_name_with_extension)
    urllib.request.urlretrieve(audio_file_url, audio_file_name_with_extension, show_progress)

    # cover
    song_art_url = soup.find('img', {'id': f'song-art{song_id}'}).get('src').replace('/112/112/', '/500/500/')
    urllib.request.urlretrieve(song_art_url, COVER_FILE_NAME, show_progress)

    # genres
    genres = set([genre.text[1:] for genre in soup.find('div', {'class': 'haus-tag-container'}).find_all('a')])
    genres -= set(['original', 'remix'])
    genres = ', '.join(genres)

    # description
    # publisher
    # relase date
    song_details_div = soup.find('div', {'class': 'track-description-container'})
    song_details = song_details_div.find_all('div', {'class': 'sidebar-description'})
    for song_detail in song_details:
        publisher_or_date = song_detail.find('strong')

        # case: description or licence
        if publisher_or_date is None:
            publisher_or_date = song_detail.find('div', {'class': 'sidebar-license'})

            # case: description
            if publisher_or_date is None:
                song_description = song_detail.text

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

    if (audio_file_type == '.mp3'):

        audio = MP3(audio_file_name_with_extension, ID3=ID3)

        if audio.tags is None:
            audio.tags = ID3()

        # remove already embedded cover(s)
        # remove existing comment(s)
        cover_keys = [key for key in audio.keys() if ('APIC' in key or 'COMM' in key)]
        for key in cover_keys:
            del audio.tags[key]

        # create and set comment field
        try:
            audio.tags['COMM::eng'] = COMM()
            audio.tags['COMM::eng'].text = [song_description]
        except Exception as e:
            logger.error(e)

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

        audio = EasyID3(audio_file_name_with_extension)
        # print(audio.keys())
        # print(audio.pprint())
        audio['title'] = song_name
        audio['artist'] = uploader
        audio['date'] = upload_date
        audio['website'] = url
        audio['genre'] = genres

        if track_number > 0:
            audio['tracknumber'] = str(track_number)

        try:
            audio['copyright'] = publisher
            audio['organization'] = publisher
        except Exception as e:
            logger.error(e)

        audio.save()

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
        download_single_url(f'https://remix.audio/track/{song_id}', track_number=count)


def show_progress(block_num, block_size, total_size):
    print(f'{round(block_num * block_size / total_size * 100, 2)}%', end='\r')


def init():
    delete_cover_file()


def delete_cover_file():
    if os.path.isfile(COVER_FILE_NAME):
        os.unlink(COVER_FILE_NAME)


def to_file_path_safe_string(unsafe_string: str) -> str:
    return re.sub(r"[/\\?%*:|\"<>\x7F\x00-\x1F]", "_", unsafe_string)


if __name__ == '__main__':
    # wav playlist https://remix.audio/playlist/2859
    # print(EasyID3.valid_keys.keys())
    main()
