"""
ui/styles.py

Application stylesheet injection for the Shiny for Python interface.

The project does not currently include a static assets directory, so the
stylesheet is provided as a Python string and injected into the application
via shiny.ui.tags.style(STYLESHEET).

The design follows a typography-first approach:
- white background
- generous whitespace
- restrained borders
- green accent colour
- accessible typography
- responsive behaviour

No Bootstrap theme overrides are used.
"""

from __future__ import annotations

from shiny import ui


STYLESHEET = """
/* ==========================================================================
   Global application styling
   ========================================================================== */

:root {
    --colour-background: #ffffff;
    --colour-card-background: #eaf7ec; 
    --colour-link: #1a56db; 
    --colour-link-hover-bg: #eaf1ff;  
    --colour-surface: #ffffff;
    --colour-text: #1f2933;
    --colour-text-muted: #52606d;
    --colour-border: #d9e2ec;
    --colour-border-light: #edf2f7;
    --colour-accent: #2f855a;
    --colour-accent-dark: #276749;
    --colour-accent-light: #f0fff4;
    --colour-highlight: #fff3bf;

    --font-family:
        "Inter",
        "Segoe UI",
        Roboto,
        Helvetica,
        Arial,
        sans-serif;

    --spacing-xs: 0.25rem;
    --spacing-sm: 0.5rem;
    --spacing-md: 1rem;
    --spacing-lg: 1.5rem;
    --spacing-xl: 2.5rem;
    --spacing-xxl: 4rem;

    --radius-small: 4px;
    --radius-medium: 8px;
}


/* ==========================================================================
   Base document styling
   ========================================================================== */

html,
body {
    background: var(--colour-background);
    color: var(--colour-text);
    font-family: var(--font-family);
    font-size: 16px;
    line-height: 1.6;
    margin: 0;
    padding: 0;
}


body {
    min-height: 100vh;
}


*,
*::before,
*::after {
    box-sizing: border-box;
}


a {
    color: var(--colour-accent-dark);
    text-decoration: none;
}


a:hover,
a:focus {
    text-decoration: underline;
}


:focus-visible {
    outline:
        3px solid rgba(47, 133, 90, 0.35);
    outline-offset: 2px;
}


/* ==========================================================================
   Main application container
   ========================================================================== */

.app-container {
    max-width: 100%;
    width: 100%;
    margin: 0;
    padding:
        var(--spacing-xl)
        var(--spacing-lg);
}


.app-header {
    margin-bottom: var(--spacing-xxl);
}


.app-title {
    color: var(--colour-text);
    font-size: clamp(2rem, 4vw, 2.8rem);
    font-weight: 600;
    letter-spacing: -0.02em;
    line-height: 1.2;
    margin: 0 0 var(--spacing-md);
}


.app-description {
    color: var(--colour-text-muted);
    font-size: 1.1rem;
    max-width: 100%;
}

.app-version {
    color: var(--colour-text-muted);
    font-size: 0.85rem;
}


.about-details {
    color: var(--colour-link);
    font-size: 0.85rem;
}


.about-summary {
    color: var(--colour-link);
    cursor: pointer;
    font-weight: 500;
    list-style: none;
}


.about-summary::-webkit-details-marker {
    display: none;
}


.about-summary::after {
    content: " ▾";
font-size: 0.75rem;
}


.about-details[open] .about-summary::after {
    content: " ▴";
}


.about-content {
    background: #fafafa;
    border: 1px solid var(--colour-border-light);
    border-radius: var(--radius-small);
    margin-top: 0.75rem;
    max-width: 720px;
    padding: 0.9rem 1rem;
}


.about-content p {
    margin: 0 0 0.65rem;
}


.about-content p:last-child {
    margin-bottom: 0;
}


.app-subtitle {
    color: var(--colour-text-muted);
    font-size: 1.1rem;
    max-width: 100%;
    margin: 0;
}

.search-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-md);
    margin-bottom: var(--spacing-xl);
}

.control-title {
    display: block;
    font-weight: 700;
    font-size: 0.95rem;
    color: var(--colour-text);
    margin-bottom: var(--spacing-xs);
}

.search-hint {
    color: var(--colour-text-muted);
    font-size: 0.85rem;
    white-space: pre-line;
    margin: var(--spacing-xs) 0 0;
}

.glossary-selector {
    margin-top: var(--spacing-md);
}

/* ==========================================================================
   Search interface
   ========================================================================== */

.search-container {
    margin-bottom: var(--spacing-xl);
}


.search-input {
    background: var(--colour-surface);
    border:
        1px solid var(--colour-border);
    border-radius: var(--radius-medium);
    color: var(--colour-text);
    font-size: 1rem;
    padding:
        0.85rem
        1rem;
    transition:
        border-color 0.15s ease,
        box-shadow 0.15s ease;
    width: 100%;
}


.search-input:hover {
    border-color: #9fb3c8;
}


.search-input:focus {
    border-color: var(--colour-accent);
    box-shadow:
        0 0 0 3px rgba(47, 133, 90, 0.15);
    outline: none;
}


.search-button {
    background: var(--colour-accent);
    border: none;
    border-radius: var(--radius-medium);
    color: white;
    cursor: pointer;
    font-size: 1rem;
    font-weight: 500;
    margin-top: var(--spacing-md);
    padding:
        0.75rem
        1.5rem;
    transition:
        background-color 0.15s ease;
}


.search-button:hover {
    background: var(--colour-accent-dark);
}


.search-button:disabled {
    cursor: not-allowed;
    opacity: 0.6;
}


.search-input-container {
    position: relative;
}

.search-input-wrapper {
    position: relative;
}

.glossary-autocomplete {
    display: none;
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    z-index: 9999;

    background: #ffffff;
    border: 1px solid var(--colour-border);
    border-top: none;
    border-radius: 0 0 var(--radius-medium) var(--radius-medium);

    max-height: 300px;
    overflow-y: auto;

    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.08);
}

.glossary-autocomplete-item {
    padding: 8px 12px;
    cursor: pointer;
    background: #ffffff;
}

.glossary-autocomplete-item:hover {
    background: #f0f0f0;
}

.pagination-controls {
    margin-top: var(--spacing-sm);
    justify-content: flex-start;
}

.pagination-button {
    background: var(--colour-surface);
    border: 1px solid var(--colour-border);
    border-radius: var(--radius-small);
    color: var(--colour-text);
    font-size: 0.8rem;
    padding: 0.25rem 0.6rem;
}

.pagination-button:hover {
    background: var(--colour-accent-light);
    border-color: var(--colour-accent);
}

/* ==========================================================================
   Result cards
   ========================================================================== */

.results-container {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-lg);
}


.result-card {
    background: var(--colour-card-background);
    border:
        1px solid var(--colour-border-light);
    border-left:
        3px solid var(--colour-accent);
    border-radius: var(--radius-small);
    padding:
        var(--spacing-lg);
    transition:
        box-shadow 0.15s ease;
}


.result-card:hover {
    box-shadow:
        0 4px 12px rgba(15, 23, 42, 0.06);
}


.result-card-title {
    color: var(--colour-text);
    font-size: 1.1rem;
    font-weight: 600;
    margin:
        0 0 var(--spacing-sm);
}


.result-card-text {
    color: var(--colour-text);
    margin: 0;
}

.result-footer {
    margin-top: var(--spacing-md);
    padding-top: var(--spacing-sm);
    border-top: 1px solid rgba(31, 41, 51, 0.1);
    font-size: 0.8rem;
    color: var(--colour-text-muted);
}

.result-footer-label {
    font-weight: 600;
    margin-right: var(--spacing-xs);
}

.result-doi-link {
    color: var(--colour-accent-dark);
    font-weight: 600;
}


/* ==========================================================================
   Glossary links and highlighting
   ========================================================================== */

.glossary-link {
    color: var(--colour-link);
    cursor: pointer;
    font-weight: 700;
    text-decoration:
        underline;
    text-decoration-thickness: 1px;
}


.glossary-link:hover,
.glossary-link:focus {
    background:
        var(--colour-link-hover-bg);
}


.search-highlight {
    background:
        var(--colour-highlight);
    border-radius: 2px;
    font-weight: 700;
    padding:
        0.05em
        0.15em;
}


/* ==========================================================================
   Metadata and filters
   ========================================================================== */

.filter-panel {
    background:
        #fafafa;
    border:
        1px solid var(--colour-border-light);
    border-radius: var(--radius-medium);
    padding: var(--spacing-lg);
    margin-bottom: var(--spacing-xl);
}


.filter-label {
    color: var(--colour-text-muted);
    font-size: 0.9rem;
    font-weight: 500;
}

.app-meta {
    display: flex;
    flex-direction: column;  
    align-items: flex-start; 
    gap: 0.25rem;             
    margin-bottom: var(--spacing-md);
}


/* ==========================================================================
   Empty states and messages
   ========================================================================== */

.empty-state {
    color: var(--colour-text-muted);
    padding:
        var(--spacing-xxl)
        var(--spacing-lg);
    text-align: center;
}


.error-message {
    background:
        #fff5f5;
    border:
        1px solid #fed7d7;
    border-radius: var(--radius-medium);
    color:
        #9b2c2c;
    padding:
        var(--spacing-md);
}


/* ==========================================================================
   Footer
   ========================================================================== */

.app-footer {
    border-top: 1px solid var(--colour-border-light);
    color: var(--colour-text-muted);
    font-size: 0.8rem;
    margin-top: var(--spacing-xxl);
    padding: var(--spacing-lg) 0 0.5rem;
}


.footer-inner {
    align-items: flex-start;
    display: flex;
    gap: var(--spacing-lg);
}


.footer-label {
    font-weight: 500;
}


.footer-separator {
    color: #9aa5b1;
}


.footer-link {
    color: #3f6f99;
}


.footer-link:hover,
.footer-link:focus {
    color: var(--colour-accent-dark);
}


.footer-credit {
    color: #52606d;
    text-align: right;
}


/* ==========================================================================
   Responsive design
   ========================================================================== */

@media (max-width: 768px) {

    .app-container {
        padding:
            var(--spacing-lg)
            var(--spacing-md);
    }


    .app-title {
        font-size: 2rem;
    }


    .result-card {
        padding:
            var(--spacing-md);
    }


    .search-button {
        width: 100%;
    }

        .footer-inner {
        align-items: flex-start;
        flex-direction: column;
    }


    .footer-credit {
        text-align: left;
    }
}


/* ==========================================================================
   Reduced motion accessibility
   ========================================================================== */

@media (prefers-reduced-motion: reduce) {

    *,
    *::before,
    *::after {
        scroll-behaviour: auto !important;
        transition-duration: 0.01ms !important;
        animation-duration: 0.01ms !important;
    }
}
"""


def app_css() -> ui.Tag:
    """
    Return the stylesheet as a Shiny UI tag.

    Usage
    -----
    Add this in the application's UI definition:

    ui.head_content(stylesheet_tag())

    Returns
    -------
    shiny.ui.Tag
        A <style> tag containing the application CSS.
    """
    return ui.tags.style(STYLESHEET)