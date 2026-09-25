import os
from docx import Document

folder_path = "/home/annabell/Documents/IPBES/2026_Document_search_engine/Github_files/data/docx/"

with open("heading_levels.txt", "w") as out:
    for filename in os.listdir(folder_path):
        if filename.endswith(".docx") and not filename.startswith("~$"):
            full_path = os.path.join(folder_path, filename)
            doc = Document(full_path)
            out.write(f"\n--- {filename} ---\n")
            for p in doc.paragraphs:
                if p.style.name.startswith("Heading"):
                    out.write(f"{p.style.name} - {p.text}\n")