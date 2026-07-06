"""Digest file generation — saves content text with metadata for Claude Code to summarize."""

from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn

from feedworm.config import get_transcripts_dir
from feedworm.database import Content, Source


def save_digest(
    content: Content,
    source: Source,
    digest_text: str,
    output_dir: Path | None = None,
) -> Path:
    """Save a digest as a markdown file (works for podcasts and articles)."""
    output_dir = output_dir or get_transcripts_dir()

    source_dir = output_dir / content.source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    output_path = source_dir / f"{content.id}_digest.md"

    # Format published date
    pub_date = ""
    if content.published_at:
        pub_date = content.published_at.strftime("%Y-%m-%d")

    if content.kind == "article":
        lines = [
            f"# Article: {content.title}",
            "",
            f"**Source:** {source.title}",
            f"**URL:** {content.url}",
        ]
    else:
        lines = [
            f"# Digest: {content.title}",
            "",
            f"**Podcast:** {source.title}",
        ]
    if pub_date:
        lines.append(f"**Date:** {pub_date}")
    lines.extend([
        "",
        "---",
        "",
        digest_text,
    ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def digest_content(
    items: list[tuple[Content, Source]],
) -> list[tuple[Content, Path | None, str | None]]:
    """
    Generate digests for multiple content items with progress tracking.

    Args:
        items: List of (content, source) tuples

    Returns:
        List of (content, path_if_success, error_if_failed) tuples
    """
    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
    ) as progress:
        task = progress.add_task(
            f"[green]Digesting {len(items)} items...", total=len(items)
        )

        for content, source in items:
            progress.update(task, description=f"[cyan]Digesting: {content.title[:40]}...")
            try:
                if not content.text_path:
                    raise ValueError("Content has no text")

                text_path = Path(content.text_path)
                if not text_path.exists():
                    raise FileNotFoundError(f"Text not found: {text_path}")

                text = text_path.read_text(encoding="utf-8")
                path = save_digest(content, source, text)
                results.append((content, path, None))
            except Exception as e:
                results.append((content, None, str(e)))
            progress.update(task, advance=1)

    return results
