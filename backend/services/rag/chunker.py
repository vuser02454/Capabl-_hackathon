"""Stage 2 — chunking.

Splits each document on markdown headings rather than on a fixed character window.

That choice matters for citation quality. A fixed window cuts mid-sentence and mid-table, so a
retrieved chunk arrives without the heading that says what it is about — and the user is shown an
excerpt that reads as if it answers a question it may not. Heading-aligned chunks always carry
their own title, which is also what makes a chunk id (`document#section-slug`) meaningful.

Oversized sections are split further on paragraph boundaries, keeping the heading on each part,
so a long section degrades into several well-labelled chunks instead of one unusable blob.
"""

import re
from dataclasses import dataclass
from typing import List, Optional

from services.rag.loader import Document

#: Characters. Above this a section is split on paragraph boundaries. Chosen so a chunk stays
#: quotable in a UI panel without scrolling — retrieval that returns a page is not retrieval.
MAX_CHUNK_CHARS = 1100

#: Sections shorter than this are folded into the next one: a bare heading with one line under it
#: retrieves badly and tells the reader nothing.
MIN_CHUNK_CHARS = 80

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, traceable to an exact section of an exact document."""

    #: `<document_id>#<section-slug>`. Stable across rebuilds, so a stored citation still resolves.
    chunk_id: str
    document_id: str
    document_title: str
    domain: str
    source: Optional[str]
    #: The heading this passage sits under, e.g. "Turbidity".
    section: str
    text: str


def _slug(value: str) -> str:
    return _SLUG_STRIP.sub("-", value.strip().lower()).strip("-") or "section"


def _split_long(text: str, limit: int) -> List[str]:
    """Paragraph-boundary split for an oversized section. Never cuts mid-paragraph."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    parts: List[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit and current:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts or [text]


def chunk_document(document: Document, max_chars: int = MAX_CHUNK_CHARS) -> List[Chunk]:
    """One document -> its heading-aligned chunks."""
    headings = list(_HEADING.finditer(document.text))
    if not headings:
        return [
            Chunk(
                chunk_id=f"{document.document_id}#{_slug(document.title)}",
                document_id=document.document_id,
                document_title=document.title,
                domain=document.domain,
                source=document.source,
                section=document.title,
                text=document.text.strip(),
            )
        ]

    sections: List["tuple[str, str]"] = []
    for index, match in enumerate(headings):
        title = match.group(2).strip()
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(document.text)
        body = document.text[start:end].strip()
        if not body:
            continue
        # A heading with almost nothing under it is folded forward rather than indexed alone.
        if sections and len(body) < MIN_CHUNK_CHARS:
            previous_title, previous_body = sections[-1]
            sections[-1] = (previous_title, f"{previous_body}\n\n{title}\n{body}")
            continue
        sections.append((title, body))

    chunks: List[Chunk] = []
    seen: dict = {}
    for title, body in sections:
        for part_index, part in enumerate(_split_long(body, max_chars)):
            base = _slug(title)
            # Two sections can share a heading ("Water" under two documents' action lists), so a
            # suffix keeps chunk ids unique and therefore resolvable.
            count = seen.get(base, 0)
            seen[base] = count + 1
            slug = base if count == 0 and part_index == 0 else f"{base}-{count + part_index + 1}"
            chunks.append(
                Chunk(
                    chunk_id=f"{document.document_id}#{slug}",
                    document_id=document.document_id,
                    document_title=document.title,
                    domain=document.domain,
                    source=document.source,
                    # The heading travels with every part of a split section.
                    section=title,
                    text=f"{title}\n\n{part}".strip(),
                )
            )
    return chunks


def chunk_documents(documents: List[Document], max_chars: int = MAX_CHUNK_CHARS) -> List[Chunk]:
    chunks: List[Chunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, max_chars))
    return chunks
