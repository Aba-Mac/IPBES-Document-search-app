"""
ui.glossary

Provides optional glossary UI components.

Glossary terms are now exposed through the main document
search box using Selectize suggestions.
"""

from __future__ import annotations

from shiny import ui


def build_glossary_panel():
    """
    Build optional glossary information panel.
    """

    return ui.div(
        ui.h3(
            "Glossary",
            class_="section-title",
        ),
        ui.p(
            (
                "Glossary terms can be searched directly "
                "from the document search box."
            ),
            class_="section-description",
        ),
        class_="glossary-panel",
    )