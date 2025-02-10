"""
Usage:
    remix.audio_dl.py <URL> [--debug | --error]
    remix.audio_dl.py -h | --help
    remix.audio_dl.py
Options:
    -h --help     Show this screen.
"""
import logging
import os
import sys
import urllib
from datetime import datetime

import requests
import mutagen
from docopt import docopt
from bs4 import BeautifulSoup
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, COMM
from mutagen.mp3 import MP3

COVER_FILE_NAME = 'cover.jpg'

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def main():
    init()
    arguments = docopt(__doc__)

    if arguments["--debug"]:
        logger.level = logging.DEBUG
    elif arguments["--error"]:
        logger.level = logging.ERROR

    url = arguments['<URL>']
    if not validate_url(url):
        sys.exit(1)

    download_url(url)
    sys.exit(0)


def validate_url(url: str) -> bool:
    return True


def url_type(url: str) -> str:
    pass


def download_url(url: str):
    download_single_url(url)


def download_single_url(url: str):
    x = requests.get(url)
    text = x.text
    # print(text)
    soup = BeautifulSoup(text, "html.parser")

    # upload date
    # song id
    upload_date_div = soup.find("div", {"class": "timeago"})
    # 2025-02-03T10:23:47+00:00 -> 2025-02-03
    upload_date = upload_date_div.get("title")[:10]
    song_id = upload_date_div.parent.get("id").replace("time", "")
    print(upload_date)

    # file url
    # file name
    play_button_div = soup.find("div", {"id": f"play{song_id}"})
    audio_file_url = play_button_div.get("data-track-url")
    audio_file_name = play_button_div.get("data-track-name")
    urllib.request.urlretrieve(audio_file_url, audio_file_name, show_progress)

    # cover
    song_art_url = soup.find("img", {"id": f"song-art{song_id}"}).get("src").replace("/112/112/", "/500/500/")
    urllib.request.urlretrieve(song_art_url, COVER_FILE_NAME, show_progress)

    # genres
    genres = set([genre.text[1:] for genre in soup.find("div", {"class": "haus-tag-container"}).find_all("a")])
    genres -= set(["original", "remix"])
    genres = ", ".join(genres)
    print(genres)

    # description
    song_details_div = soup.find("div", {"class": "track-description-container"})
    song_details = song_details_div.find_all("div", {"class": "sidebar-description"})

    for song_detail in song_details:
        publisher_or_date = song_detail.find("strong")
        if publisher_or_date is None:
            song_description = song_detail.text
        elif 'Record label' in song_detail.text:
            publisher = publisher_or_date.text
        elif 'Release date' in song_detail.text:
            release_date = publisher_or_date.text
            d = datetime.strptime(release_date, '%B %d, %Y')
            upload_date = d.strftime('%Y-%m-%d')



    # uploader
    uploader = soup.find("a", {"id": f"song-author{song_id}"}).text
    print(uploader)

    # title
    song_name = soup.find("div", {"id": f"song-name{song_id}"}).text


    audio = MP3(audio_file_name, ID3=ID3)

    if audio.tags is None:
        audio.tags = ID3()

    # remove already embedded cover(s)
    # remove existing comment(s)
    cover_keys = [key for key in audio.keys() if ('APIC' in key or 'COMM' in key)]
    for key in cover_keys:
        del audio.tags[key]


    # create and set comment field
    try:
        audio.tags["COMM::eng"] = COMM()
        audio.tags["COMM::eng"].text = [song_description]
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

    audio = EasyID3(audio_file_name)
    # print(audio.keys())
    # print(audio.pprint())
    audio["title"] = song_name
    audio["artist"] = uploader
    audio["date"] = upload_date
    audio["website"] = url
    audio["genre"] = genres

    try:
        audio["copyright"] = publisher
        audio["organization"] = publisher
    except Exception as e:
        logger.error(e)

    audio.save()

    delete_cover_file()


def show_progress(block_num, block_size, total_size):
    print(f'{round(block_num * block_size / total_size * 100, 2)}%', end="\r")


def init():
    delete_cover_file()

def delete_cover_file():
    if os.path.isfile(COVER_FILE_NAME):
        os.unlink(COVER_FILE_NAME)


if __name__ == '__main__':
    # print(EasyID3.valid_keys.keys())
    main()
