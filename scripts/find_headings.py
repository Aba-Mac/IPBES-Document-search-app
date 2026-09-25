import os
from docx import Document
from core.paths import DOCX_DIR

with open("heading_levels.txt", "w") as out:
    for filename in os.listdir(DOCX_DIR):
        if filename.endswith(".docx") and not filename.startswith("~$"):
            full_path = os.path.join(DOCX_DIR, filename)
            doc = Document(full_path)
            out.write(f"\n--- {filename} ---\n")
            for p in doc.paragraphs:
                if p.style.name.startswith("Heading"):
                    out.write(f"{p.style.name} - {p.text}\n")