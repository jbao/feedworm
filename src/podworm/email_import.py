"""Email-based ingestion of forwarded Xiaoyuzhou episode shares.

Polls an IMAP mailbox (iCloud Mail by default) for messages forwarded by the user
that contain xiaoyuzhoufm.com episode (or podcast) links, and feeds them into
the standard download/transcribe pipeline. Called once per day by the `daily`
command. Standard IMAP only — no provider-specific extensions.
"""

from __future__ import annotations

import email
import email.header
import imaplib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from email.message import Message
from email.utils import parseaddr

from podworm.database import Database, Episode
from podworm.feed_parser import scrape_episode_page, scrape_podcast_page

log = logging.getLogger(__name__)

URL_RE = re.compile(
    r"https?://(?:www\.)?xiaoyuzhoufm\.com/(?:episode|podcast)/[a-zA-Z0-9]+"
)


@dataclass
class IncomingMessage:
    uid: bytes
    message_id: str
    subject: str
    sender: str
    xyz_urls: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    subject: str
    url: str
    status: str  # queued | dup | error | no-url
    detail: str = ""
    episode: Episode | None = None


def connect(host: str, user: str, password: str) -> imaplib.IMAP4_SSL:
    m = imaplib.IMAP4_SSL(host)
    m.login(user, password)
    m.select("INBOX")
    return m


def _imap_date(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def _decode_bytes(payload: bytes, charset: str | None) -> str:
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _decode_body(msg: Message) -> str:
    parts: list[str] = []
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() in ("text/plain", "text/html"):
                payload = p.get_payload(decode=True)
                if payload:
                    parts.append(_decode_bytes(payload, p.get_content_charset()))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            parts.append(_decode_bytes(payload, msg.get_content_charset()))
    return "\n".join(parts)


def _decode_subject(raw: str | None) -> str:
    if not raw:
        return ""
    out: list[str] = []
    for chunk, charset in email.header.decode_header(raw):
        if isinstance(chunk, bytes):
            out.append(_decode_bytes(chunk, charset))
        else:
            out.append(chunk)
    return "".join(out)


def search_candidates(
    m: imaplib.IMAP4_SSL,
    allowed_sender: str,
    on_date: date,
) -> list[IncomingMessage]:
    criteria = (
        f'FROM "{allowed_sender}" '
        f'SUBJECT "xiaoyuzhou" '
        f'ON {_imap_date(on_date)}'
    )
    typ, data = m.uid("SEARCH", criteria)
    if typ != "OK":
        raise RuntimeError(f"IMAP SEARCH failed: {typ}")
    raw_uids = data[0] if data and data[0] else b""
    uids = raw_uids.split() if raw_uids else []

    out: list[IncomingMessage] = []
    for uid in uids:
        # BODY.PEEK[] fetches the full message without setting \Seen; iCloud
        # silently drops the body when asked via the legacy RFC822 item.
        typ, fetch_data = m.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not fetch_data:
            log.warning("IMAP FETCH failed for uid %r: %s", uid, typ)
            continue
        # FETCH returns a list of mixed shapes: (envelope_bytes, body_bytes)
        # tuples interleaved with bare bytes (e.g., the closing b')' line).
        raw: bytes | None = None
        for item in fetch_data:
            if (
                isinstance(item, tuple)
                and len(item) >= 2
                and isinstance(item[1], (bytes, bytearray))
            ):
                raw = bytes(item[1])
                break
        if raw is None:
            log.warning("FETCH response missing body for uid %r: %r", uid, fetch_data)
            continue
        msg = email.message_from_bytes(raw)

        sender = parseaddr(msg.get("From", ""))[1].lower()
        message_id = (msg.get("Message-ID") or "").strip()
        subject = _decode_subject(msg.get("Subject"))
        body = _decode_body(msg)
        urls = sorted(set(URL_RE.findall(body)))

        out.append(IncomingMessage(
            uid=uid,
            message_id=message_id,
            subject=subject,
            sender=sender,
            xyz_urls=urls,
        ))
    return out


def mark_processed(m: imaplib.IMAP4_SSL, uid: bytes) -> None:
    """Mark message as read. DB metadata is the authoritative dedup; \\Seen is a visual indicator."""
    m.uid("STORE", uid, "+FLAGS", "(\\Seen)")


def _ingest_url(db: Database, url: str) -> Episode:
    if "/episode/" in url:
        podcast, episode = scrape_episode_page(url)
    else:
        podcast, eps = scrape_podcast_page(url)
        if not eps:
            raise ValueError("podcast page had no episodes")
        episode = eps[0]
    db.add_podcast(podcast)
    db.add_episode(episode)
    return episode


def import_from_email(
    db: Database,
    *,
    on_date: date,
    host: str,
    user: str,
    password: str,
    allowed_sender: str,
) -> list[ImportResult]:
    """Search the IMAP mailbox for forwarded shares received on `on_date` and ingest them.

    Returns one ImportResult per (email, url) pair so the caller can render a
    summary table. New episodes have `result.episode` populated for the
    download phase to pick up.
    """
    results: list[ImportResult] = []
    m = connect(host, user, password)
    try:
        candidates = search_candidates(m, allowed_sender, on_date)
        for inc in candidates:
            if inc.sender != allowed_sender.lower():
                # IMAP FROM filter already narrows this; defense-in-depth check.
                log.warning("Skipping uid %r: sender %s != %s", inc.uid, inc.sender, allowed_sender)
                continue

            if not inc.xyz_urls:
                results.append(ImportResult(inc.subject, "", "no-url"))
                continue

            all_ok = True
            for url in inc.xyz_urls:
                # Per-URL dedup so a multi-link email partially-ingested last run
                # picks up the remaining URLs on retry.
                dedup_key = f"email:{inc.message_id}:{url}"
                if existing_id := db.get_metadata(dedup_key):
                    existing = db.get_episode(existing_id)
                    results.append(ImportResult(
                        inc.subject, url, "dup",
                        existing.title[:60] if existing else "",
                        episode=existing if existing and not existing.downloaded_at else None,
                    ))
                    continue

                try:
                    episode = _ingest_url(db, url)
                    db.set_metadata(dedup_key, episode.id)
                    results.append(ImportResult(
                        inc.subject, url, "queued", episode.title[:60], episode=episode,
                    ))
                except Exception as e:
                    all_ok = False
                    log.exception("Failed to ingest %s", url)
                    results.append(ImportResult(inc.subject, url, "error", str(e)[:80]))

            if all_ok:
                try:
                    mark_processed(m, inc.uid)
                except Exception as e:
                    log.warning("Failed to mark uid %r seen: %s", inc.uid, e)
    finally:
        try:
            m.logout()
        except Exception:
            pass

    return results
