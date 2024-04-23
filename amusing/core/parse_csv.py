import os
import re
import time
import subprocess

import pandas as pd
import yt_dlp
from sqlalchemy.orm import Session
from ytmusicapi import YTMusic

from amusing.db.models import Album, Song

ytmusic = YTMusic()

def add_metadata(
    input_file,
    output_file,
    album_dir,
    title=None,
    album=None,
    artist=None,
    genre=None,
    track=None,
    tracks=None,
):
    subprocess.run([
        'ffmpeg',
        '-y',
        '-i', input_file,
        '-metadata', f"title={title}",
        '-metadata', f"album={album}",
        '-metadata', f"artist={artist}",
        '-metadata', f"genre={genre}",
        '-metadata', f"track={track}/{tracks}",
        '-acodec', 'copy',
        '-vcodec', 'png',
        '-disposition:v', 'attached_pic',
        '-vf', "crop=w='min(iw\,ih)':h='min(iw\,ih)',scale=600:600,setsar=1",
        output_file
    ])

def process_groups(
    album_name, album_dir, group, session, album=None, dir_already_present=False
):
    """Helper function to process each album and songs present within it from the csv."""
    print(f"Processing album: {album_name}")
    files_in_album = os.listdir(album_dir)
    for index, row in group.iterrows():
        song_name = row["Name"].replace('/', u"\u2215")
        artist_name = row["Artist"].replace('/', u"\u2215")
        genre = row["Genre"]
        track = row["Track Number"]
        tracks = row["Track Count"]

        if dir_already_present:
            song_already_present = False
            for file_name in files_in_album:
                if (song_name.lower() in file_name.lower()):
                    song_already_present = True
                    print(f"Song downloaded already. Skipping '{song_name}'.")
                    break
            if song_already_present:
                continue

        # Perform operations on the row
        print(
            f"Processing song: '{song_name}', Album='{album_name}', Artist='{artist_name}'"
        )
        try:
            search_results = ytmusic.search(
                f"{song_name} - {artist_name} - {album_name}",
                limit=1,
                ignore_spelling=True,
                filter="songs",
            )
            videoId = search_results[0]["videoId"]
            song_url = f"https://www.youtube.com/watch?v={videoId}"
            ydl_opts = {
                "format": "m4a/bestaudio/best",
                # ℹ️ See help(yt_dlp.postprocessor) for a list of available Postprocessors and their arguments
                "postprocessors": [
                    {  # Extract audio using ffmpeg
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "m4a",
                    }
                ],
                "outtmpl": f"{album_dir}/{song_name}.%(ext)s",
                "postprocessors": [
                    {"already_have_thumbnail": False, "key": "EmbedThumbnail"}
                ],
                "write_thumbnail": True,
                "writethumbnail": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                error_code = ydl.download(song_url)
                print("Error=> ", error_code)

            add_metadata(
                os.path.join(album_dir, f"{song_name}.m4a"),
                os.path.join(album_dir, '..', '..', 'songs', f"{song_name}.m4a"),
                album_dir,
                title=song_name,
                album=album_name,
                artist=artist_name,
                genre=genre,
                track=track,
                tracks=tracks,
            )

            # check if song present in db, if yes, remove and add this one.
            song_query = (
                session.query(Song)
                .filter_by(name=song_name, artist=artist_name, album=album)
                .first()
            )
            if song_query:
                session.delete(song_query)
            song = Song(
                name=song_name, artist=artist_name, video_id=videoId, album=album
            )
            session.add(song)
            session.commit()
            print(
                f"Done song: '{song_name}', Album='{album_name}', Artist='{artist_name}'"
            )
        except Exception as e:
            print(f"Exception {e}. Skipping '{song_name}'.")
            continue
    print(f"Done album '{album_name}'")


def process_csv(filename: str, download_path: str, session: Session):
    """Function to read CSV, process rows, and sleep accordingly."""
    df = pd.read_csv(filename)
    grouped = df.groupby("Album")

    songs_dir = os.path.join(download_path, 'songs')
    if not (os.path.exists(songs_dir) and os.path.isdir(songs_dir)):
        os.makedirs(songs_dir, exist_ok=True)

    for album_name, group in grouped:
        album_name = album_name.replace('/', u"\u2215")
        album_dir = os.path.join(download_path, 'albums', album_name)
        dir_already_present = False
        if os.path.exists(album_dir) and os.path.isdir(album_dir):
            dir_already_present = True
        else:
            os.makedirs(album_dir, exist_ok=True)

        album = session.query(Album).filter_by(name=album_name).first()
        if not album:
            album = Album(name=album_name)
            session.add(album)
            session.commit()

        # Submit the group processing task to the ThreadPoolExecutor
        process_groups(album_name, album_dir, group, session, album, dir_already_present)
