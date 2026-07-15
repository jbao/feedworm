# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Content-digest CLI tool (**feedworm**). Ingests podcast episodes (小宇宙/Xiaoyuzhou, Spotify) and web articles, turns each into text (transcribe audio / extract HTML), writes a markdown digest, and generates summaries for review in Claude Code, an Obsidian note, or email.

The project was renamed from `podworm`; the package now lives in `src/feedworm/` and the CLI is `feedworm`. Legacy `PODWORM_*` env vars and the `~/.local/share/podworm` data dir are still read as fallbacks so existing data isn't orphaned.

## Commands

Run with `uv run feedworm <command>`. Key commands:

- `daily` — Full pipeline: Spotify import → podcast email import → article-link email import → download → transcribe/extract → digest → clean → summarize (one combined digest)
- `articles [URLS... | -f FILE]` — Summarize a list of article links (ingest → extract → digest → summarize). Flags `--obsidian` / `--email` / `--no-chat` mirror `daily`.
- `reset -y` — Wipe all data (db, audio, transcripts)
- `chat -d YYYY-MM-DD` — Launch Claude Code with transcripts from a date
- `shownotes <AUDIO_PATH>` — Generate publishable shownotes (title, summary, timestamped chapters, takeaways, links) from a local recording. Standalone: reuses `transcribe_audio` + `claude --print`, bypasses the feed/DB pipeline. Flags: `--language/-L`, `--output/-o`.
- `transcribe` — Transcribe downloaded episodes (standalone)
- `sync` — Download new episodes from RSS feeds
- `grab <podcast> <episode>` — Search and download a specific episode

## Environment Variables

Required: `DEEPGRAM_API_KEY`
Optional: `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `FEEDWORM_DATA_DIR` (legacy: `PODWORM_DATA_DIR`), `FEEDWORM_OBSIDIAN_VAULT` (legacy: `PODWORM_OBSIDIAN_VAULT`)
Email ingestion (all optional; daily skips these steps if creds unset): `IMAP_USER`, `IMAP_PASSWORD` (Apple ID app-specific password), `IMAP_HOST` (default `imap.mail.me.com`), `EMAIL_ALLOWED_SENDER` (default `jie.bao@gmail.com`), `EMAIL_ARTICLE_SUBJECT` (default `read` — subject keyword marking an email as carrying article links)
Email-out summary: `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`

## Email-based ingestion

`daily` polls the IMAP account (`IMAP_USER`, iCloud Mail by default) for messages received on the run date from `EMAIL_ALLOWED_SENDER`, matched by subject keyword:

- **Podcasts** (subject contains `xiaoyuzhou`): `xiaoyuzhoufm.com/episode|podcast/...` URLs are extracted and fed through `feed_parser.scrape_episode_page` into the download/transcribe pipeline.
- **Articles** (subject contains `EMAIL_ARTICLE_SUBJECT`): any `https?://` links in the body are extracted (filtered against asset/homepage URLs) and fed through `article.extract_article`.

Both paths share the IMAP plumbing in `email_import.py` (`_run_import`). Processed messages are marked `\Seen`; DB metadata key `email:<Message-ID>:<url>` is the authoritative dedup. Standard IMAP only (no Gmail extensions), so `IMAP_HOST` can be repointed at any IMAPS:993 server.

## Architecture

All source in `src/feedworm/`. CLI entry point: `cli.py` (Click framework, Rich for UI).

The data model is a unified **`Content`** item (podcast episode OR article) belonging to a **`Source`** (podcast feed OR website), discriminated by a `kind` field (`podcast`/`article`, `podcast`/`website`). Pipeline stages are tracked by timestamp columns in SQLite (`~/.local/share/feedworm/podcasts.db`) and dispatch on `kind`:

1. **Import** — `feed_parser.py` / `spotify.py` (podcasts) or `article.ingest_article_url` (articles) → adds Source + Content rows
2. **Acquire text** —
   - podcast: **Download** (`downloader.py`, async httpx, sets `acquired_at` + `media_path`) → **Transcribe** (`transcriber.py`, Deepgram nova-2, sets `text_ready_at` + `text_path`)
   - article: **Extract** (`article.py`, trafilatura with httpx fallback, sets `text_ready_at` + `text_path` in one step)
3. **Digest** — `digest.py` → `save_digest`/`digest_content` write a kind-aware header + text as `{id}_digest.md`, set `digested_at`
4. **Summarize/deliver** — `cli._summarize_and_deliver` feeds all of the day's digests (both kinds) to `claude --print`, delivering one combined Obsidian note and/or email (subject `☕ Daily digest {date}`)
5. **Clean** — deletes media (`media_path`) for podcast content only

Database ORM: `database.py` with `Content`/`Source` dataclasses over `sqlite-utils`. `_migrate_legacy_schema` renames the pre-rename `podcasts`/`episodes` tables and their audio-centric columns in place (idempotent), preserving ids so existing metadata keys stay valid.

Output files: `~/.local/share/feedworm/transcripts/{source_id}/{content_id}.md`

## No automated test suite

`test_favorites.py` is a manual script for Xiaoyuzhou API auth testing, not part of a test framework.
