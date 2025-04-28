# utils.py
import os
import shutil
from yt_dlp import YoutubeDL
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

def get_video_info(url):
    """
    Use yt-dlp to fetch video info (metadata, formats) without downloading.
    Returns the info dictionary.
    """
    ydl_opts = {"quiet": True, "no_warnings": True}
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info

def select_formats(info, num_formats=3):
    """
    From yt-dlp info, select the top video formats and one best audio format.
    Returns a list of format dicts.
    """
    formats = info.get("formats", [])
    # Filter out video formats (having a video codec) and sort by resolution (height)
    video_fmts = [f for f in formats if f.get("vcodec") != "none" and f.get("height")]
    # Sort by height (resolution) descending
    video_fmts.sort(key=lambda f: f.get("height", 0), reverse=True)
    # Take top N distinct resolutions
    selected = []
    seen_heights = set()
    for f in video_fmts:
        h = f.get("height")
        if h not in seen_heights:
            seen_heights.add(h)
            selected.append(f)
        if len(selected) >= num_formats:
            break
    # Select best audio-only format (no video codec), sort by bitrate
    audio_fmts = [f for f in formats if f.get("vcodec") == "none"]
    if audio_fmts:
        # Sort by total bitrate or audio bitrate
        audio_fmts.sort(key=lambda f: f.get("tbr", 0), reverse=True)
        selected.append(audio_fmts[0])
    return selected

def download_format(url, format_id, download_dir):
    """
    Download the given URL using yt-dlp, selecting only the specified format.
    Saves into download_dir and returns the filepath.
    """
    ydl_opts = {
        "format": format_id,
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    # yt-dlp prints the filename when done; we can reconstruct it
    # The outtmpl uses title and ext from info
    title = info.get("title", "video")
    ext = info.get("ext", "")
    filename = f"{title}.{ext}"
    # Some formats (like dash) may create separate files; pick the actual downloaded file
    filepath = os.path.join(download_dir, filename)
    if not os.path.exists(filepath):
        # If file not found, try alternative: sometimes yt-dlp names files differently
        # (fallback to last downloaded file in directory)
        files = os.listdir(download_dir)
        if files:
            filepath = os.path.join(download_dir, files[-1])
    return filepath

def start_http_server(directory, host, port):
    """
    Start a simple HTTP server in a background thread to serve the given directory.
    """
    # Ensure the directory exists
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    httpd = HTTPServer((host, port), handler)
    print(f"Starting HTTP server at http://{host}:{port}/ (serving {directory})")
    # Run in a daemon thread so it doesn't block program exit
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()