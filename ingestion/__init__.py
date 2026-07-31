"""
Document ingestion package.

Implements the complete document ingestion pipeline:

    OCR (when required)
        → document extraction
        → text cleaning
        → section-aware chunking
        → metadata extraction
        → glossary exact-match indexing

The ingestion pipeline produces clean paragraph-level records ready for
database storage and subsequent topic tagging.
"""