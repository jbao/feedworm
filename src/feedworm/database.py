"""SQLite database for storing content (podcast episodes + articles) metadata."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlite_utils

from feedworm.config import get_db_path, ensure_dirs


@dataclass
class Source:
    """A content source — a podcast feed or an article website."""

    id: str
    title: str
    url: str  # feed URL (podcast) or site/home URL (website)
    kind: str = "podcast"  # "podcast" | "website"
    description: str | None = None
    author: str | None = None
    image_url: str | None = None
    added_at: datetime | None = None


@dataclass
class Content:
    """A single content item — a podcast episode or an article."""

    id: str
    source_id: str
    title: str
    url: str  # audio enclosure (podcast) or article page URL (article)
    kind: str = "podcast"  # "podcast" | "article"
    description: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    acquired_at: datetime | None = None  # audio downloaded / article fetched
    text_ready_at: datetime | None = None  # transcript / extracted text available
    media_path: str | None = None  # downloaded audio (podcast only)
    text_path: str | None = None  # transcript OR extracted article text
    digest_path: str | None = None
    digested_at: datetime | None = None


SCHEMA = """
-- Sources table (podcast feeds + article websites)
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'podcast',
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    author TEXT,
    image_url TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Content table (podcast episodes + articles)
CREATE TABLE IF NOT EXISTS content (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    kind TEXT NOT NULL DEFAULT 'podcast',
    title TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    duration_seconds INTEGER,
    published_at TIMESTAMP,
    acquired_at TIMESTAMP,
    text_ready_at TIMESTAMP,
    media_path TEXT,
    text_path TEXT,
    digest_path TEXT,
    digested_at TIMESTAMP
);

-- Metadata table for app state (e.g., last_auto_run)
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_content_source ON content(source_id);
CREATE INDEX IF NOT EXISTS idx_content_acquired ON content(acquired_at);
CREATE INDEX IF NOT EXISTS idx_content_text ON content(text_ready_at);
"""


class Database:
    """Database operations for feedworm."""

    def __init__(self, db_path: Path | None = None):
        """Initialize database connection."""
        ensure_dirs()
        self.db_path = db_path or get_db_path()
        self.db = sqlite_utils.Database(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        """Migrate any legacy schema, then ensure the current schema exists."""
        self._migrate_legacy_schema()
        for statement in SCHEMA.split(";"):
            statement = statement.strip()
            if statement:
                self.db.execute(statement)
        self._ensure_columns()

    def _migrate_legacy_schema(self) -> None:
        """Rename the pre-`Content` tables/columns in place (idempotent).

        Older databases used `podcasts`/`episodes` with audio-centric column
        names. Content ids are preserved, so existing metadata keys (spotify
        mapping, email dedup) remain valid.
        """
        tables = set(self.db.table_names())
        if "podcasts" in tables and "sources" not in tables:
            self.db.execute("ALTER TABLE podcasts RENAME TO sources")
        if "episodes" in tables and "content" not in tables:
            self.db.execute("ALTER TABLE episodes RENAME TO content")

        self._rename_column("sources", "feed_url", "url")
        self._rename_column("content", "podcast_id", "source_id")
        self._rename_column("content", "audio_url", "url")
        self._rename_column("content", "downloaded_at", "acquired_at")
        self._rename_column("content", "audio_path", "media_path")
        self._rename_column("content", "transcribed_at", "text_ready_at")
        self._rename_column("content", "transcript_path", "text_path")

    def _rename_column(self, table: str, old: str, new: str) -> None:
        """Rename a column if the old name is present and the new one isn't."""
        if table not in set(self.db.table_names()):
            return
        cols = {c.name for c in self.db[table].columns}
        if old in cols and new not in cols:
            try:
                self.db.execute(
                    f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'
                )
            except Exception:
                pass

    def _ensure_columns(self) -> None:
        """Add columns introduced after the initial schema (migration)."""
        for table, col in (
            ("sources", "kind TEXT NOT NULL DEFAULT 'podcast'"),
            ("content", "kind TEXT NOT NULL DEFAULT 'podcast'"),
            ("content", "digest_path TEXT"),
            ("content", "digested_at TIMESTAMP"),
        ):
            try:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
            except Exception:
                pass

    # Source operations

    def add_source(self, source: Source) -> None:
        """Add or update a source."""
        self.db["sources"].insert(
            {
                "id": source.id,
                "kind": source.kind,
                "title": source.title,
                "url": source.url,
                "description": source.description,
                "author": source.author,
                "image_url": source.image_url,
                "added_at": source.added_at or datetime.now().isoformat(),
            },
            replace=True,
        )

    def get_source(self, source_id: str) -> Source | None:
        """Get a source by ID."""
        try:
            return self._row_to_source(self.db["sources"].get(source_id))
        except sqlite_utils.db.NotFoundError:
            return None

    def list_sources(self) -> list[Source]:
        """List all sources."""
        return [self._row_to_source(row) for row in self.db["sources"].rows]

    def delete_source(self, source_id: str) -> None:
        """Delete a source and its content."""
        self.db["content"].delete_where("source_id = ?", [source_id])
        self.db["sources"].delete_where("id = ?", [source_id])

    def _row_to_source(self, row: dict) -> Source:
        return Source(
            id=row["id"],
            title=row["title"],
            url=row["url"],
            kind=row.get("kind") or "podcast",
            description=row["description"],
            author=row["author"],
            image_url=row["image_url"],
            added_at=row["added_at"],
        )

    # Content operations

    def add_content(self, content: Content) -> None:
        """Add or update a content item."""
        self.db["content"].insert(
            {
                "id": content.id,
                "source_id": content.source_id,
                "kind": content.kind,
                "title": content.title,
                "description": content.description,
                "url": content.url,
                "duration_seconds": content.duration_seconds,
                "published_at": (
                    content.published_at.isoformat()
                    if content.published_at
                    else None
                ),
                "acquired_at": (
                    content.acquired_at.isoformat() if content.acquired_at else None
                ),
                "text_ready_at": (
                    content.text_ready_at.isoformat()
                    if content.text_ready_at
                    else None
                ),
                "media_path": content.media_path,
                "text_path": content.text_path,
                "digest_path": content.digest_path,
                "digested_at": (
                    content.digested_at.isoformat() if content.digested_at else None
                ),
            },
            replace=True,
        )

    def get_content(self, content_id: str) -> Content | None:
        """Get a content item by ID."""
        try:
            return self._row_to_content(self.db["content"].get(content_id))
        except sqlite_utils.db.NotFoundError:
            return None

    def list_content(self, source_id: str | None = None) -> list[Content]:
        """List content, optionally filtered by source."""
        if source_id:
            rows = self.db["content"].rows_where(
                "source_id = ?", [source_id], order_by="-published_at"
            )
        else:
            rows = self.db["content"].rows_where(order_by="-published_at")
        return [self._row_to_content(row) for row in rows]

    def list_content_to_download(
        self, kind: str = "podcast", limit: int | None = None
    ) -> list[Content]:
        """List content that hasn't been acquired yet (podcast audio to download)."""
        rows = self.db["content"].rows_where(
            "acquired_at IS NULL AND kind = ?",
            [kind],
            order_by="-published_at",
            limit=limit,
        )
        return [self._row_to_content(row) for row in rows]

    def list_content_to_transcribe(
        self, limit: int | None = None
    ) -> list[Content]:
        """List podcast content that has been downloaded but not transcribed."""
        rows = self.db["content"].rows_where(
            "acquired_at IS NOT NULL AND text_ready_at IS NULL AND kind = 'podcast'",
            order_by="-published_at",
            limit=limit,
        )
        return [self._row_to_content(row) for row in rows]

    def list_content_to_extract(self, limit: int | None = None) -> list[Content]:
        """List article content that hasn't had its text extracted yet."""
        rows = self.db["content"].rows_where(
            "text_path IS NULL AND kind = 'article'",
            order_by="-published_at",
            limit=limit,
        )
        return [self._row_to_content(row) for row in rows]

    def mark_content_acquired(self, content_id: str, media_path: str) -> None:
        """Mark content as acquired (audio downloaded)."""
        self.db["content"].update(
            content_id,
            {"acquired_at": datetime.now().isoformat(), "media_path": media_path},
        )

    def mark_content_text(self, content_id: str, text_path: str) -> None:
        """Mark content as having its text ready (transcript or extracted article)."""
        now = datetime.now().isoformat()
        row = self.db["content"].get(content_id)
        update = {"text_ready_at": now, "text_path": text_path}
        # Articles get their text in one step, without a separate acquire phase.
        if not row.get("acquired_at"):
            update["acquired_at"] = now
        self.db["content"].update(content_id, update)

    def list_content_to_digest(self, limit: int | None = None) -> list[Content]:
        """List content that has text ready but hasn't been digested."""
        rows = self.db["content"].rows_where(
            "text_ready_at IS NOT NULL AND digested_at IS NULL",
            order_by="-published_at",
            limit=limit,
        )
        return [self._row_to_content(row) for row in rows]

    def mark_content_digested(self, content_id: str, digest_path: str) -> None:
        """Mark content as digested."""
        self.db["content"].update(
            content_id,
            {"digested_at": datetime.now().isoformat(), "digest_path": digest_path},
        )

    def list_content_to_clean(self, source_id: str | None = None) -> list[Content]:
        """List transcribed content that still has media files on disk."""
        query = "text_ready_at IS NOT NULL AND media_path IS NOT NULL"
        params: list = []
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        rows = self.db["content"].rows_where(query, params, order_by="-published_at")
        return [self._row_to_content(row) for row in rows]

    def clear_media_path(self, content_id: str) -> None:
        """Clear the media_path for content (after deleting the file)."""
        self.db["content"].update(content_id, {"media_path": None})

    def _row_to_content(self, row: dict) -> Content:
        """Convert a database row to a Content object."""
        return Content(
            id=row["id"],
            source_id=row["source_id"],
            kind=row.get("kind") or "podcast",
            title=row["title"],
            description=row["description"],
            url=row["url"],
            duration_seconds=row["duration_seconds"],
            published_at=(
                datetime.fromisoformat(row["published_at"])
                if row["published_at"]
                else None
            ),
            acquired_at=(
                datetime.fromisoformat(row["acquired_at"])
                if row["acquired_at"]
                else None
            ),
            text_ready_at=(
                datetime.fromisoformat(row["text_ready_at"])
                if row["text_ready_at"]
                else None
            ),
            media_path=row["media_path"],
            text_path=row["text_path"],
            digest_path=row.get("digest_path"),
            digested_at=(
                datetime.fromisoformat(row["digested_at"])
                if row.get("digested_at")
                else None
            ),
        )

    # Content counts

    def count_content(self, source_id: str) -> int:
        """Count total content items for a source."""
        return self.db.execute(
            "SELECT COUNT(*) FROM content WHERE source_id = ?", [source_id]
        ).fetchone()[0]

    def count_with_text(self, source_id: str) -> int:
        """Count content items with text ready for a source."""
        return self.db.execute(
            "SELECT COUNT(*) FROM content WHERE source_id = ? AND text_ready_at IS NOT NULL",
            [source_id],
        ).fetchone()[0]

    # Metadata operations

    def get_metadata(self, key: str) -> str | None:
        """Get a metadata value."""
        result = self.db.execute(
            "SELECT value FROM metadata WHERE key = ?", [key]
        ).fetchone()
        return result[0] if result else None

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata value."""
        self.db["metadata"].insert({"key": key, "value": value}, replace=True)

    def get_last_auto_run(self) -> datetime | None:
        """Get the timestamp of the last auto run."""
        value = self.get_metadata("last_auto_run")
        return datetime.fromisoformat(value) if value else None

    def set_last_auto_run(self, timestamp: datetime | None = None) -> None:
        """Set the timestamp of the last auto run."""
        self.set_metadata("last_auto_run", (timestamp or datetime.now()).isoformat())
