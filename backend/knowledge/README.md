# Knowledge corpus

The documents in this directory are the retrieval corpus for `services/rag/`.

**Every document restates knowledge that is already encoded in this codebase**, and each section
names the file it was taken from. Nothing here was sourced from the open web, and no external
publication is quoted. That constraint is deliberate: a retriever that cites a document nobody
can check is worse than no retriever at all, because the citation makes the claim look verified.

If you add a document:

1. It must be knowledge this project can actually stand behind — an encoded threshold, a measured
   result in `runs/`, or a documented policy choice.
2. It must carry a `Source:` line naming the file or report it came from.
3. Rebuild the index: the retriever rebuilds automatically on startup when the corpus changes.

Document ids are the filename stem. Chunk ids are `<document_id>#<section-slug>`, so any citation
in the API resolves to an exact section of an exact file.
