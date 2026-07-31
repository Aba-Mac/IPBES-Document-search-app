"""
Search package.

Implements the application's exact-search engine using SQLite FTS5.

Responsibilities include:

- Boolean query parsing
- Boolean expression evaluation
- FTS5 query generation
- Result retrieval
- Result ranking
- Search service orchestration

The search engine intentionally performs lexical search only.
Glossary matching, highlighting, hyperlink generation, and semantic
ranking are handled by separate modules.
"""