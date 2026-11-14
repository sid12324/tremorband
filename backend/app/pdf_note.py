"""A small PDF for a clinician note. The text is the stored markdown."""

from __future__ import annotations


def note_pdf(text: str) -> bytes:
    """Return a one-font PDF whose pages contain the note text."""
    lines = text.replace("\r", "").split("\n") or [""]
    pages: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        current.append(line[:110])
        if len(current) >= 48:
            pages.append(current)
            current = []
    if current or not pages:
        pages.append(current)
    objects: list[bytes] = []

    def add(body: str | bytes) -> int:
        raw = body.encode("latin-1", errors="replace") if isinstance(body, str) else body
        objects.append(raw)
        return len(objects)

    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for page_lines in pages:
        commands = ["BT", "/F1 11 Tf", "50 780 Td"]
        for index, line in enumerate(page_lines):
            if index:
                commands.append("0 -14 Td")
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({safe}) Tj")
        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_ids.append(
            add(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        )
    for content_id in content_ids:
        page_ids.append(
            add(
                "<< /Type /Page /Parent PAGES /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            )
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    pages_id = add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>")
    # Parent references were a placeholder. Rewrite page objects now that the pages id is known.
    for page_id in page_ids:
        objects[page_id - 1] = objects[page_id - 1].replace(b"/Parent PAGES", f"/Parent {pages_id} 0 R".encode("latin-1"))
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n")
    xref = sum(len(chunk) for chunk in chunks)
    xref_lines = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n \n")
    chunks.append("".join(xref_lines).encode("latin-1"))
    chunks.append(
        f"trailer << /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "latin-1"
        )
    )
    return b"".join(chunks)
