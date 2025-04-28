# config.py
# Configuration for the Telegram bot and downloader.

# Telegram bot token (replace with your actual token)
TOKEN = "7952616197:AAFST8tx1_pG3BplY_VJBTyK8BAYpiSK4eo"

# Directory to save downloaded files
DOWNLOAD_DIR = "downloads"

# HTTP server settings for serving large files
HOST = "0.0.0.0"         # Listen on all interfaces
PORT = 8000              # Port for HTTP server
BASE_URL = f"http://34.122.26.12:{PORT}/"  # External URL (VM's IP) to access files