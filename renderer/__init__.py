"""
Rendering package.

Transforms search results into presentation-ready content for the
Shiny user interface.

Responsibilities include:

- search-term highlighting
- glossary hyperlink generation from precomputed matches
- safe HTML generation
- preservation of paragraph formatting
- rendering utilities shared by UI components

The rendering package contains no search logic and performs no
database queries beyond consuming precomputed rendering metadata.
"""