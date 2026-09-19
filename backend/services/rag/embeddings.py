"""Stage 3 — embeddings.

TF-IDF vectors over the corpus vocabulary, computed with numpy and nothing else.

WHY NOT A NEURAL EMBEDDING MODEL
--------------------------------
Three reasons, in order of weight:

1. **The demo must not be able to fail.** A hosted embedding API adds a network dependency to the
   analysis path; a local transformer adds a large dependency and a model download. This corpus is
   seven short technical documents in a fixed vocabulary — the regime where lexical retrieval is
   strongest and dense retrieval buys least.
2. **It is deterministic.** The same query returns the same chunks in the same order, every time.
   That is worth a great deal when the retrieval is shown on screen.
3. **It is inspectable.** Every score decomposes into terms a reader can see. A cosine distance
   between two 384-dimensional vectors cannot be argued with; a TF-IDF match on "turbidity" can.

These are **sparse lexical embeddings**, and the API says so rather than implying a semantic model
is running. The honest name for the technique is the one used here.

The vectoriser is deliberately self-contained rather than pulled from scikit-learn: the whole of
it is ~60 lines, and adding a large dependency to avoid them would be a poor trade in a project
that already ships torch for a reason.
"""

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

#: Words carrying no retrieval signal in a technical corpus.
#:
#: Deliberately conservative about meaning-bearing terms: "not" stays, because "not established"
#: is one of the most important phrases in this corpus, and stripping it would make the passage
#: about what evidence CANNOT show match a query about what it can.
#:
#: Interrogatives are included, and they are not optional. The corpus is full of headings like
#: "What an image can and cannot establish", so "what" is a frequent corpus term with a non-zero
#: IDF. Left in, the off-topic query "what is the capital of France" matched three chunks at 0.24
#: on the word "what" alone — a retriever citing sources for a question the corpus cannot answer,
#: which is the exact failure this pipeline is supposed to avoid.
STOP_WORDS = frozenset({
    # articles, conjunctions, prepositions, copulas
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for", "from", "had", "has",
    "have", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "those", "to", "was", "were", "will", "with",
    # interrogatives and generic modals — see the note above
    "what", "how", "why", "when", "where", "which", "who", "whom", "whose",
    "do", "does", "did", "can", "could", "should", "would", "may", "might", "must",
})

_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]*")


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens, stop words removed.

    Keeps `.`, `_` and `-` inside tokens so `pm2.5`, `visible_surface_litter` and `non-degrading`
    survive as single terms. Splitting those would lose exactly the vocabulary this corpus is
    about.
    """
    return [token for token in _TOKEN.findall(text.lower()) if token not in STOP_WORDS]


@dataclass
class TfidfEmbedder:
    """Fitted TF-IDF vectoriser. `fit` builds the vocabulary; `embed` maps text into it."""

    vocabulary: Dict[str, int]
    idf: List[float]

    @classmethod
    def fit(cls, corpus: Sequence[str]) -> "TfidfEmbedder":
        vocabulary: Dict[str, int] = {}
        document_frequency: Dict[int, int] = {}

        for text in corpus:
            seen = set()
            for token in tokenize(text):
                index = vocabulary.setdefault(token, len(vocabulary))
                seen.add(index)
            for index in seen:
                document_frequency[index] = document_frequency.get(index, 0) + 1

        total = max(1, len(corpus))
        # Smoothed IDF: +1 inside the log keeps a term appearing in every document at a small
        # positive weight rather than exactly zero, so an all-common-terms query still ranks.
        idf = [0.0] * len(vocabulary)
        for index in range(len(vocabulary)):
            frequency = document_frequency.get(index, 0)
            idf[index] = math.log((1 + total) / (1 + frequency)) + 1.0
        return cls(vocabulary=vocabulary, idf=idf)

    @property
    def dimensions(self) -> int:
        return len(self.vocabulary)

    def embed(self, text: str):
        """Text -> an L2-normalised TF-IDF vector over the fitted vocabulary.

        Terms absent from the vocabulary are dropped: they carry no corpus evidence, and the
        alternative (extending the vocabulary at query time) would make scores incomparable
        between queries.
        """
        import numpy as np

        vector = np.zeros(len(self.vocabulary), dtype="float32")
        counts: Dict[int, int] = {}
        for token in tokenize(text):
            index = self.vocabulary.get(token)
            if index is not None:
                counts[index] = counts.get(index, 0) + 1
        if not counts:
            return vector

        # Sublinear term frequency: a term repeated eight times is not eight times the evidence.
        for index, count in counts.items():
            vector[index] = (1.0 + math.log(count)) * self.idf[index]

        norm = float(np.linalg.norm(vector))
        # L2 normalisation makes the dot product a cosine similarity, so long documents do not
        # outrank short ones purely for being long.
        return vector / norm if norm > 0 else vector

    def embed_all(self, texts: Sequence[str]):
        import numpy as np

        if not texts:
            return np.zeros((0, len(self.vocabulary)), dtype="float32")
        return np.vstack([self.embed(text) for text in texts])
