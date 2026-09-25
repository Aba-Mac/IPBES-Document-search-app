"""
draft_metadata.py

Propose document metadata for manual review. Writes document_metadata_draft.csv.
"""
import csv
import re

from docx import Document
from docx.table import Table

from core.paths import DOCX_DIR, SECTION_DOI_DIR
from ingestion.extractor import _iter_block_items, _table_text

MONTH = ("January|February|March|April|May|June|July|August|"
         "September|October|November|December")
DATE_RE = re.compile(
    rf"\d{{1,2}}(?:\s+(?:{MONTH}))?(?:\s*(?:[-\u2013\u2014]|to|and)\s*\d{{1,2}})?"
    rf"(?:\s+(?:{MONTH}))?\s+(?:19|20)\d{{2}}",
    re.I,
)
CIT_START = re.compile(r"Suggested\s+citation\s*:?\s*", re.I)
CIT_HEAD = re.compile(r"IPBES\s*\(\s*((?:19|20)\d{2})\s*\)\s*[.:]?\s*", re.I)
END_LABELS = re.compile(r"\s*(?:Disclaimer|Compiled by|Cover photo)\s*:", re.I)
HELD_RE = re.compile(
    r",?\s*held\s+in\s+(.+?)\s*,?\s*(?:on|from|between)\s*$", re.I
)


def find_citation(texts: list[str]) -> str | None:
    for i, text in enumerate(texts):
        m = CIT_START.search(text)
        if not m:
            continue
        parts = [text[m.end():]]
        for nxt in texts[i + 1: i + 4]:          
            if DATE_RE.search(" ".join(parts)) or END_LABELS.match(nxt):
                break
            parts.append(nxt)
        joined = " ".join(" ".join(parts).split())
        return END_LABELS.split(joined, maxsplit=1)[0].strip()
    return None


def parse_citation(citation: str) -> dict:
    head = CIT_HEAD.search(citation)
    year = int(head.group(1)) if head else None
    body = (citation[head.end():] if head else citation).strip(" .")

    dates = list(DATE_RE.finditer(body))
    if not dates:
        return {"year": year}

    d = dates[-1]
    before = body[: d.start()].rstrip(" ,")
    after = body[d.end():].strip(" ,.")

    location = None
    held = HELD_RE.search(before)
    if after:                                  
        location = after
    elif held:                                 
        location, before = held.group(1).strip(" ,"), before[: held.start()]
    else:                                      
        rest, _, tail = before.rpartition(". ")
        if rest and len(tail) <= 60:
            location, before = tail, rest

    before = re.sub(r",?\s*held(?:\s+in)?\s*$", "", before.strip(" ,."), flags=re.I)
    title = before.rpartition(". ")[2].strip(" ,.") or None
    return {"year": year, "title": title, "date": d.group(0), "location": location}


def main() -> None:
    rows = []
    for path in sorted(DOCX_DIR.glob("*.docx")):
        if path.name.startswith("~$"):
            continue
        blocks = _iter_block_items(Document(path))
        texts = [
            (_table_text(b) if isinstance(b, Table) else b.text).strip()
            for b in blocks
        ]
        texts = [t for t in texts if t][:80]
        citation = find_citation(texts)
        parsed = parse_citation(citation) if citation else {}
        rows.append({
            "filename": path.name,
            "title": parsed.get("title") or "",
            "year": parsed.get("year") or "",
            "date": parsed.get("date") or "",
            "location": parsed.get("location") or "",
            "citation_raw": citation or "NOT FOUND",  
        })

    out = SECTION_DOI_DIR.with_name("document_metadata_draft.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {out} - review and save as document_metadata.csv")


if __name__ == "__main__":
    main()