"""Article ingestion + extraction for the ``article`` content kind.

Mirrors the podcast download+transcribe stages, but collapses them into one
step: fetch the page, extract the main text, and record it as the content's
text (``text_path`` + ``text_ready_at``). Uses trafilatura for extraction with
a crude httpx fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn

from feedworm.config import get_transcripts_dir
from feedworm.database import Content, Database, Source

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


@dataclass
class ExtractedArticle:
    title: str
    text: str
    published_at: datetime | None = None
    author: str | None = None


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def content_id_for(url: str) -> str:
    """Stable id for an article, derived from its URL (dedup-friendly)."""
    return "art_" + _hash(url)


def source_id_for(url: str) -> str:
    """Stable id for the website an article belongs to (per host)."""
    netloc = urlparse(url).netloc.lower()
    return "web_" + _hash(netloc)


# --- Extraction ---


def _fallback_extract(url: str) -> tuple[str | None, str | None]:
    """Best-effort extraction without trafilatura: strip tags from the HTML."""
    try:
        resp = httpx.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None, None
    html = resp.text
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = title_match.group(1).strip() if title_match else None
    # Drop scripts/styles, then all tags, then collapse whitespace.
    body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return (body or None), title


def extract_article(url: str) -> ExtractedArticle:
    """Fetch a URL and extract the main article text + metadata."""
    import trafilatura

    text = title = author = None
    published_at: datetime | None = None

    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        raw = trafilatura.extract(
            downloaded,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            include_tables=True,
        )
        if raw:
            obj = json.loads(raw)
            text = obj.get("text")
            title = obj.get("title")
            author = obj.get("author")
            if obj.get("date"):
                try:
                    published_at = datetime.fromisoformat(obj["date"])
                except (ValueError, TypeError):
                    published_at = None

    if not text:
        text, title = _fallback_extract(url)

    if not text or not text.strip():
        raise ValueError(f"Could not extract article text from {url}")

    return ExtractedArticle(
        title=(title or url).strip(),
        text=text.strip(),
        published_at=published_at,
        author=author,
    )


# --- Ingestion ---


def ingest_article_url(db: Database, url: str) -> Content:
    """Create Source(kind=website) + Content(kind=article) rows for a URL.

    Idempotent: returns the existing Content if the URL was already ingested.
    """
    cid = content_id_for(url)
    if existing := db.get_content(cid):
        return existing

    netloc = urlparse(url).netloc.lower()
    sid = source_id_for(url)
    if not db.get_source(sid):
        db.add_source(
            Source(
                id=sid,
                title=netloc or "web",
                url=f"https://{netloc}" if netloc else url,
                kind="website",
            )
        )

    content = Content(id=cid, source_id=sid, title=url, url=url, kind="article")
    db.add_content(content)
    return content


def _save_text(content: Content, article: ExtractedArticle, output_dir: Path) -> Path:
    """Write the extracted article body to the transcripts tree."""
    source_dir = output_dir / content.source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    output_path = source_dir / f"{content.id}.md"
    output_path.write_text(
        f"# {article.title}\n\n{article.text}\n", encoding="utf-8"
    )
    return output_path


def extract_articles(
    db: Database,
    items: list[Content],
) -> list[tuple[Content, Path | None, str | None]]:
    """Extract text for article content, persisting text + refreshed metadata.

    For each item: fetch + extract, write the text file, update the content's
    title/published_at, and mark it text-ready. Returns (content, path, error).
    """
    results: list[tuple[Content, Path | None, str | None]] = []
    output_dir = get_transcripts_dir()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task(
            f"[green]Extracting {len(items)} articles...", total=len(items)
        )
        for content in items:
            progress.update(
                task, description=f"[cyan]Extracting: {content.title[:40]}..."
            )
            try:
                article = extract_article(content.url)
                path = _save_text(content, article, output_dir)
                # Refresh the title/date now that we have real metadata.
                content.title = article.title
                if article.published_at:
                    content.published_at = article.published_at
                db.add_content(content)
                db.mark_content_text(content.id, str(path))
                results.append((content, path, None))
            except Exception as e:
                results.append((content, None, str(e)))
            progress.update(task, advance=1)

    return results
