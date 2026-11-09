"""Turn text into embeddings, using a free model that runs on this machine."""

from functools import lru_cache

# A multilingual model, so a question in Uzbek can match a passage in English.
# Changing the model requires a migration and processing every document again.
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_DIMENSIONS = 384


@lru_cache(maxsize=1)
def _get_model():
    # Imported here because loading it takes seconds and much memory, and
    # most commands, such as migrate, never need it.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def _embed(texts):
    vectors = _get_model().encode(texts, normalize_embeddings=True, batch_size=32)
    return vectors.tolist()


# This model family expects the prefixes "passage: " and "query: ".
def embed_passages(texts):
    return _embed([f"passage: {text}" for text in texts])


def embed_query(text):
    return _embed([f"query: {text}"])[0]
