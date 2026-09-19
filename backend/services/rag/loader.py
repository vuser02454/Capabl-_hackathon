"""Stage 1 — document loading.

Reads the knowledge corpus from `backend/knowledge/*.md`. Every document carries YAML-ish front
matter giving its title, domain and the file in this repository the knowledge came from.

The `source` field is not decoration. A retrieved chunk is shown to a user as a citation, and a
citation that cannot be resolved is worse than no citation at all — it makes an unverified claim
look checked. So a document without a `source` is loaded but flagged, and the retriever reports
the flag rather than silently presenting it as sourced.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("ecosentinel.rag.loader")

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"

#: Files that describe the corpus rather than being part of it.
EXCLUDED = {"README.md"}

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Document:
    """One loaded knowledge document."""

    #: Filename stem. Stable, and what a citation resolves against.
    document_id: str
    title: str
    #: air | water | waste | cross_signal — used to bias retrieval toward the active domain.
    domain: str
    #: The file in this repository this knowledge was taken from.
    source: Optional[str]
    text: str
    path: Path
    warnings: List[str] = field(default_factory=list)


def _parse_front_matter(raw: str) -> "tuple[Dict[str, str], str]":
    match = _FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip().lower()] = value.strip()
    return meta, raw[match.end():]


def load_documents(directory: Optional[Path] = None) -> List[Document]:
    """Every `.md` in the corpus directory, front matter parsed.

    Never raises on one bad file: an unreadable document is logged and skipped, because a corpus
    that fails to load would take down an analysis that does not depend on it.
    """
    root = Path(directory or KNOWLEDGE_DIR)
    if not root.is_dir():
        logger.warning("rag_corpus_missing path=%s", root)
        return []

    documents: List[Document] = []
    for path in sorted(root.glob("*.md")):
        if path.name in EXCLUDED:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001 - one unreadable file must not break retrieval
            logger.warning("rag_document_unreadable path=%s", path, exc_info=True)
            continue

        meta, body = _parse_front_matter(raw)
        warnings: List[str] = []
        source = meta.get("source")
        if not source:
            warnings.append(
                "This document declares no source file, so its citations cannot be resolved."
            )
        documents.append(
            Document(
                document_id=path.stem,
                title=meta.get("title") or path.stem.replace("_", " ").title(),
                domain=(meta.get("domain") or "cross_signal").strip().lower(),
                source=source,
                text=body.strip(),
                path=path,
                warnings=warnings,
            )
        )

    logger.info("rag_corpus_loaded documents=%s path=%s", len(documents), root)
    return documents


def corpus_fingerprint(directory: Optional[Path] = None) -> str:
    """Cheap change-detector: names and modification times.

    Lets the index rebuild when a document is edited, without hashing every file on every request.
    """
    root = Path(directory or KNOWLEDGE_DIR)
    if not root.is_dir():
        return "missing"
    parts = [
        f"{path.name}:{path.stat().st_mtime_ns}"
        for path in sorted(root.glob("*.md"))
        if path.name not in EXCLUDED
    ]
    return "|".join(parts) or "empty"
