# Document Search and Glossary Application

## Overview

The **Document Search and Glossary Application** is a production-grade document discovery system built with **Shiny for Python** for deployment to **Posit Connect** via **GitHub**.

The application indexes a curated collection of approximately twenty PDF documents (up to fifty pages each), extracts structured content at paragraph level, enriches documents with metadata and topic tags, and provides a fast, Boolean-enabled full-text search experience.

The architecture is intentionally modular to support future expansion while maintaining a clear separation of concerns. Individual components—including the database layer, ingestion pipeline, topic-tagging module, search engine, and Shiny user interface—are implemented as independent modules and documented separately.

The live application currently provides **exact full-text search only** using SQLite FTS5. Infrastructure for semantic tagging and embeddings is built during ingestion but is intentionally **not used** by the search engine. This allows future migration to hybrid lexical/semantic search (for example using Elasticsearch) without reprocessing the document collection.

---

# Project Objectives

The application is designed to provide:

- Paragraph-level search rather than page-level search
- Automatic OCR of scanned PDF documents
- High-quality extraction from digital-native PDFs
- Intelligent document section detection
- Rich document metadata extraction
- Robust text cleaning prior to chunking
- Boolean full-text search
- Interactive glossary integration
- Simple typography-first interface
- Fast SQLite FTS5 indexing
- Future-ready semantic tagging infrastructure
- Deployment through GitHub to Posit Connect

---

# Technology Stack

| Component | Technology |
|-----------|------------|
| User Interface | Shiny for Python |
| Deployment | Posit Connect |
| Source Control | GitHub |
| Database | SQLite |
| Full-text Search | SQLite FTS5 |
| OCR | OCRmyPDF |
| PDF Metadata & Text | PyMuPDF |
| Document Extraction | Unstructured |
| Text Cleaning | ftfy + custom cleaning pipeline |
| Primary Chunking | Unstructured `chunk_by_title` |
| Secondary Chunking | LangChain Recursive Character Text Splitter |
| Embeddings | Sentence Transformers |
| Topic Verification | Ollama |
| Data Processing | pandas |

---

# System Architecture

```text
                     PDF Collection
                           │
                           ▼
          ┌────────────────────────────────┐
          │ Determine PDF Type             │
          │ Digital-native or Scanned      │
          └────────────────────────────────┘
                           │
             ┌─────────────┴─────────────┐
             │                           │
             ▼                           ▼
      Digital-native               Scanned PDF
             │                           │
             │                    OCRmyPDF
             │                           │
             └─────────────┬─────────────┘
                           ▼
                Document Extraction
          (Unstructured + PyMuPDF Metadata)
                           │
                           ▼
                  Text Cleaning Stage
      • Repair encoding (ftfy)
      • Remove headers and footers
      • Remove page numbers
      • Remove table-of-contents artefacts
      • Strip OCR dot leaders
      • Remove stray OCR characters
      • Normalise whitespace
      • Preserve paragraph structure
                           │
                           ▼
          Primary Chunking (chunk_by_title)
                           │
                 Poor segmentation?
                    ┌──────┴──────┐
                    │             │
                   No            Yes
                    │             │
                    ▼             ▼
               Continue     LangChain Fallback
                    └──────┬──────┘
                           ▼
                  Metadata Extraction
                           │
                           ▼
         Glossary Exact-Match Indexing
        (terms.csv → paragraph_terms)
                           │
                           ▼
           Topic Tagging & Embeddings
                           │
                           ▼
                 SQLite + SQLite FTS5
                           │
                           ▼
              Rendering Module
      (Highlighting + Hyperlink Generation)
                           │
                           ▼
               Shiny for Python Interface
```

---

# Major Modules

The application is organised into independent modules to simplify maintenance, testing and future enhancement.

This README intentionally provides only a high-level overview.

Detailed implementation of each module is documented separately.

| Module | Responsibility |
|---------|----------------|
| Configuration | Core Infrastructure (configuration, paths, environment, logging) |
| Database Layer | SQLite schema, persistence and FTS5 indexing |
| Ingestion Pipeline | OCR → extraction → cleaning → chunking → metadata → glossary exact-match indexing |
| Topic Tagging | Anchor matching, embeddings and LLM verification |
| Rendering | Search-term highlighting and glossary hyperlink generation |
| Search Engine | Boolean parsing, FTS queries and ranking |
| Shiny UI | Typography-first user interface |

---

# Core Features

## PDF Processing

The application is designed for document collections containing approximately:

- 20 PDF documents
- Maximum 50 pages per document

Each document is automatically classified as either:

- Digital-native PDF
- Scanned PDF

Scanned documents are processed with OCRmyPDF before extraction.

Digital-native documents are processed directly using Unstructured and PyMuPDF.

---

## Text Cleaning Pipeline

Following extraction, every document passes through a dedicated cleaning stage before chunking.

Cleaning includes:

- Repairing mojibake and encoding problems using **ftfy**
- Removing repeated page headers
- Removing repeated page footers
- Removing page numbers
- Removing table-of-contents artefacts
- Stripping OCR dot leaders
- Removing stray OCR symbols
- Normalising whitespace
- Preserving document paragraphs and section boundaries

This cleaning stage improves chunk quality while maintaining the original logical structure of the document.

---

## Chunking Strategy

The application uses a two-stage chunking strategy.

### Primary chunking

Unstructured's `chunk_by_title` operates on cleaned document text.

Benefits include:

- Preservation of document hierarchy
- Section-aware chunking
- Natural paragraph grouping

### Secondary chunking

When sections exceed configured limits or document structure is weak, a LangChain recursive chunker is automatically applied.

This fallback produces smaller, semantically coherent chunks while preserving metadata inherited from the original section.

---

## Metadata Extraction

Each document is enriched with structured metadata, including:

- Document title
- Publication date
- Publication year
- Plenary session
- Meeting location
- Source filename
- Page information
- OCR status
- Extraction method

Additional metadata may be added as new document collections are introduced.

---

## Search

The live application supports exact full-text search only.

Features include:

- Boolean AND
- Boolean OR
- Boolean NOT
- Boolean NOR
- Nested parentheses
- SQLite FTS5 indexing
- Paragraph-level search
- Highlighted search terms
- Hyperlinks to other glossary terms included in text

Semantic ranking is intentionally excluded from live search.

---

## Rendering

The rendering module is responsible for transforming stored search results into display-ready HTML for the Shiny interface.

Responsibilities include:

- Highlighting search terms
- Inserting glossary hyperlinks
- Preserving paragraph formatting
- Preventing nested or overlapping markup
- Generating safe HTML fragments

Separating rendering from UI components keeps presentation logic independent of application layout and simplifies testing.

---

## Glossary

Approximately one hundred glossary terms are imported from `terms.csv`.

Within search results:

- Glossary terms are automatically detected
- Terms become clickable hyperlinks
- Selecting a glossary term launches a new search for that term

---

## Topic Tagging Infrastructure

Each paragraph is processed by a dedicated topic-tagging pipeline.

The tagging process uses three successive layers:

1. Fuzzy anchor matching
2. Embedding cosine similarity
3. LLM verification for low-confidence matches

The resulting:

- Topic tags
- Confidence scores
- Embedding vectors

are stored in the database for future semantic search capabilities.

These data are intentionally excluded from the live search and ranking pipeline but provide forward-compatible infrastructure for future Elasticsearch or hybrid lexical–semantic retrieval.

---

# Project Directory Layout

```text
document-search/
│
├── app.py
├── README.md
├── requirements.txt
├── .gitignore
│
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── env.py
│   ├── logging.py
│   └── paths.py
|
├── .github/
│   └── workflows/
│       └── ci.yml
|
├── data/
│   ├── pdfs/
│   ├── glossary/
│   │   └── terms.csv
│   ├── processed/
│   ├── cache/
│   └── exports/
│
├── database/
│   ├── __init__.py
│   ├── schema.py
│   ├── repository.py
│   └── migrations.py
│
├── ingestion/
│   ├── __init__.py
│   ├── ocr.py
│   ├── extracting.py
│   ├── cleaning.py
│   ├── chunking.py
│   ├── metadata.py
│   ├── glossary.py
│   └── pipeline.py
|
├── renderer/
│   ├── __init__.py
│   ├── hyperlinks.py
│   ├── highlighting.py
│   ├── html.py
│   └── renderer.py
│
├── tagging/
│   ├── __init__.py
│   ├── anchors.py
│   ├── embeddings.py
│   ├── verifier.py
│   └── pipeline.py
│
├── search/
│   ├── __init__.py
│   ├── parser.py
│   ├── boolean.py
│   ├── ranking.py
│   └── service.py
│
├── ui/
│   ├── __init__.py
│   ├── app.py
│   ├── layouts.py
│   ├── cards.py
│   ├── search.py
│   ├── glossary.py
│   └── styles.py
│
├── utils/
│   ├── __init__.py
│   ├── filesystem.py
│   ├── text.py
│   └── validation.py
│
└── tests/
    │
    ├── __init__.py
    ├── test_database.py
    ├── test_ingestion.py
    ├── test_search.py
    ├── test_renderer.py
    ├── test_tagging.py
    └── test_ui.py
```

---

# Installation

## 1. Clone the repository

```bash
git clone https://github.com/<organisation>/<repository>.git
cd document-search
```

## 2. Create a virtual environment

Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

## 3. Install project dependencies

```bash
pip install -r requirements.txt
```

## 4. Install OCRmyPDF

Ensure OCRmyPDF is installed and available on the host operating system.

Verify installation:

```bash
ocrmypdf --version
```

## 5. Build the database

Database creation and migration are documented within the **Database Layer** module.

## 6. Ingest documents

The ingestion workflow—including OCR, extraction, cleaning, chunking and metadata enrichment—is documented in the **Ingestion Pipeline** module.

## 7. Launch the application

```bash
shiny run app.py
```

---

# Continuous Integration

The repository includes a GitHub Actions workflow from the initial project scaffold.

The CI pipeline executes automatically on every push and pull request.

The workflow performs:

- Dependency installation
- Ruff linting
- Unit testing
- Package validation

This ensures that every commit satisfies the project's coding and testing standards before deployment to Posit Connect.

---

# Deployment

The application is designed for deployment using:

```text
Developer
      │
      ▼
Git Commit
      │
      ▼
GitHub Repository
      │
      ▼
Posit Connect
      │
      ▼
Production Deployment
```

No code modifications should be required between local development and production deployment.

---

# Application Health Check

The Shiny application exposes a lightweight health-check endpoint for deployment monitoring.

The endpoint reports basic application status and is intended for use by deployment infrastructure, monitoring systems and automated availability checks.

It performs no database modifications and returns only minimal operational information required to verify that the application has started successfully.

---

# Testing

Automated tests are organised by module.

Run all tests using:

```bash
pytest
```

---

# Coding Standards

The project follows modern Python development practices, including:

- Python 3.11+
- Comprehensive type hints
- Complete module and function documentation
- Structured exception handling
- Modular architecture
- Separation of concerns
- Consistent formatting and linting
- Production-ready logging
- Maintainable package structure

---

# Future Enhancements

The architecture has been designed to accommodate future capabilities without requiring structural redesign.

Potential enhancements include:

- Elasticsearch integration
- Hybrid lexical/semantic search
- Vector search
- Cross-document semantic ranking
- Additional document collections
- Incremental indexing
- Scheduled ingestion
- Search analytics
- Saved searches
- User authentication

---

# License

Specify the appropriate project licence prior to public distribution.

---

# Acknowledgements

This project builds upon several mature open-source technologies, including:

- Shiny for Python
- Unstructured
- PyMuPDF
- OCRmyPDF
- SQLite
- LangChain
- Sentence Transformers
- ftfy
- pandas

These libraries provide the foundation for a robust, maintainable and extensible document search platform.