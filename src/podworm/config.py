"""Configuration management for podworm."""

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Get the data directory for podworm."""
    # Check environment variable first
    if env_dir := os.environ.get("PODWORM_DATA_DIR"):
        return Path(env_dir).expanduser()

    # Default to ~/.local/share/podworm
    return Path.home() / ".local" / "share" / "podworm"


def get_audio_dir() -> Path:
    """Get the directory for downloaded audio files."""
    return get_data_dir() / "audio"


def get_transcripts_dir() -> Path:
    """Get the directory for transcript files."""
    return get_data_dir() / "transcripts"


def get_db_path() -> Path:
    """Get the path to the SQLite database."""
    return get_data_dir() / "podcasts.db"


def get_groq_api_key() -> str | None:
    """Get the Groq API key from environment."""
    return os.environ.get("GROQ_API_KEY")


def get_deepgram_api_key() -> str | None:
    """Get the Deepgram API key from environment."""
    return os.environ.get("DEEPGRAM_API_KEY")


def get_spotify_client_id() -> str | None:
    """Get the Spotify client ID from environment."""
    return os.environ.get("SPOTIFY_CLIENT_ID")


def get_spotify_client_secret() -> str | None:
    """Get the Spotify client secret from environment."""
    return os.environ.get("SPOTIFY_CLIENT_SECRET")


def get_spotify_cache_path() -> Path:
    """Get the path for Spotify token cache."""
    return get_data_dir() / ".spotify_token_cache"


def get_imap_host() -> str:
    """Get the IMAP host (defaults to iCloud Mail)."""
    return os.environ.get("IMAP_HOST", "imap.mail.me.com")


def get_imap_user() -> str | None:
    """Get the IMAP username (the assistant inbox address)."""
    return os.environ.get("IMAP_USER")


def get_imap_password() -> str | None:
    """Get the IMAP password (Apple ID app-specific password for iCloud Mail)."""
    return os.environ.get("IMAP_PASSWORD")


def get_email_allowed_sender() -> str:
    """Get the only sender whose forwards are ingested."""
    return os.environ.get("EMAIL_ALLOWED_SENDER", "jie.bao@gmail.com")


def get_interviews_dir() -> Path:
    """Get the directory for interview transcripts."""
    return get_data_dir() / "interviews"


def get_obsidian_vault_dir() -> Path:
    """Get the Obsidian vault directory."""
    if env_dir := os.environ.get("PODWORM_OBSIDIAN_VAULT"):
        return Path(env_dir).expanduser()
    return Path.home() / "Documents" / "obsidian" / "Personal" / "2 - Areas"


def get_log_dir() -> Path:
    """Get the directory for log files."""
    return get_data_dir() / "logs"


def ensure_dirs() -> None:
    """Ensure all required directories exist."""
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_audio_dir().mkdir(parents=True, exist_ok=True)
    get_transcripts_dir().mkdir(parents=True, exist_ok=True)
