import os
import uuid
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
from threading import Thread
from functools import partial
import yt_dlp

def start_http_server(directory: str, port: int):
    """
    Start an HTTP server in a separate thread to serve files from the given directory.
    """
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    httpd = TCPServer(("", port), handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

def get_top_formats(url: str):
    """
    Use yt-dlp to fetch available formats for the given URL.
    Returns a tuple: (list_of_top_video_formats, best_audio_format).
    """
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    formats = info.get('formats', [])
    video_formats = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
    video_formats.sort(key=lambda f: f.get('height', 0), reverse=True)
    top_videos = video_formats[:3]
    audio_formats = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
    audio_formats.sort(key=lambda f: f.get('abr', 0), reverse=True)
    best_audio = audio_formats[0] if audio_formats else None
    return top_videos, best_audio

def download_media(url: str, format_id: str, ext: str, download_path: str) -> str:
    """
    Download the media from the URL using yt-dlp with the specified format.
    Returns the file path of the downloaded file.
    """
    os.makedirs(download_path, exist_ok=True)
    unique_name = str(uuid.uuid4())
    filename = f"{unique_name}.{ext}"
    outtmpl = os.path.join(download_path, filename)
    ydl_opts = {
        'format': str(format_id),
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return outtmpl
