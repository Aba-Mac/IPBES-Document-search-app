"""
Test suite package.

Contains unit, integration, and database integrity tests covering the
entire application.

Test modules include:

- database integrity (FTS5 synchronisation, foreign key constraints,
  migration idempotency)
- document ingestion
- topic tagging
- search engine
- rendering
- Shiny user interface

The test suite is designed to support continuous integration through
GitHub Actions and ensure production readiness.
"""