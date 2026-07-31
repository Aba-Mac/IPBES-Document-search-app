"""
Topic tagging package.

Provides paragraph-level topic classification using a three-stage
workflow:

    1. Fuzzy anchor matching
    2. Embedding cosine similarity
    3. LLM verification for low-confidence matches

The resulting topic assignments, confidence scores, and embedding
vectors are stored as forward-looking infrastructure for future
semantic search capabilities.
"""