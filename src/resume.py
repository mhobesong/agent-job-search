import os


def extract_resume_text(path: str) -> str:
    """Extract text from a resume file (PDF or plain text)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Resume not found: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in (".txt", ".md"):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    raise ValueError(f"Unsupported resume format: {ext} (use .pdf, .txt, .md)")


def _extract_pdf(path: str) -> str:
    import pdfplumber

    texts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
    return "\n".join(texts)
