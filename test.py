"""
diagnose_headers.py — standalone, run directly against a PDF.
No dependency on extract.py / ocr.py / the full pipeline.
"""
from collections import Counter

from unstructured.partition.pdf import partition_pdf

PDF_PATH = r"/home/annabell/Documents/IPBES/2026_Document_search_engine/Github_files/data/pdfs/2021 - Report of the third ILK dialogue workshop of the IPBES values assessment.pdf"  # use the already-OCR'd/searchable PDF

# Mirror _page_number()'s logic, simplified since these are raw
# partition_pdf elements (no orig_elements yet at this stage).
def page_number(element) -> int:
    metadata = getattr(element, "metadata", None)
    page = getattr(metadata, "page_number", None)
    return int(page) if page is not None else 1


elements = partition_pdf(
    filename=PDF_PATH,
    strategy="hi_res",
    infer_table_structure=True,
    include_page_breaks=False,
)

# 1. Confirm what raw elements exist right at the page 33/34 boundary,
#    and their categories, BEFORE stripping.
print("--- RAW, pre-strip ---")
for el in elements:
    pn = getattr(el.metadata, "page_number", None)
    if pn in (33, 34):
        print(pn, type(el).__name__, el.category, repr(el.text))

# 2. Run your actual stripping function and check the same window after.
from ingestion.extractor import _strip_document_noise
stripped = _strip_document_noise(elements)

print("--- AFTER _strip_document_noise ---")
for el in stripped:
    pn = getattr(el.metadata, "page_number", None)
    if pn in (33, 34):
        print(pn, type(el).__name__, el.category, repr(el.text))

# 3. Run chunk_by_title on the stripped elements and inspect the chunk
#    that should now contain the merged "They documented ... the plants..." text.
from unstructured.chunking.title import chunk_by_title
chunks = chunk_by_title(stripped, combine_text_under_n_chars=200, multipage_sections=True,
                        max_characters=1000, new_after_n_chars=800)
for c in chunks:
    if "They documented" in c.text or "the plants and their values" in c.text:
        print("--- MATCHING CHUNK ---")
        print(repr(c.text))