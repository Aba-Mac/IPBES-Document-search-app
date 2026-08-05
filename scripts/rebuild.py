"""
Maintenance utilities.

Currently reserved for rebuilding FTS indexes,
embeddings and caches.
"""

from database import repository

print(
    "Documents:",
    repository.table_row_count("documents"),
)