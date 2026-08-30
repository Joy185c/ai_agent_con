# Phase 4 — RAG / File & Image Studying

Upload a PDF or image, review/edit what got extracted from it, confirm it,
and then ask questions about it in chat — answers are grounded in the
actual document content via retrieval, not the model's general knowledge.

## What's new vs Phase 3
- `extraction.py` — text extraction pipeline:
  1. Text-based PDF → direct extraction (`pdfplumber`), no OCR at all
  2. Image / scanned PDF → **Tesseract OCR** (free, local, no API quota)
  3. Only if OCR produces too little text → one-shot **vision fallback**
     (Gemini) — this is the only path that touches a vision-capable key
- `rag.py` — chunking, local embeddings (`sentence-transformers`, no API
  key needed), and `ChromaDB` for storage/retrieval
- `db.py` — added a `documents` table linking uploaded files to conversations
- New endpoints:
  - `POST /extract` — upload a file, get back extracted text + method used
  - `POST /documents` — confirm (possibly edited) text, chunk + embed + store
  - `GET /documents?conversation_id=` / `DELETE /documents/{id}`
  - `/chat` now accepts an optional `document_id` — when present, the most
    relevant chunks are retrieved and injected as context before the model
    sees the question
- Frontend — an upload button (📎), an editable extraction-preview card
  right in the chat (edit before confirming), and a small badge showing
  which document is "attached" to the current conversation

## Setup

### 1. System dependency: Tesseract
OCR needs the Tesseract binary installed on the machine (not just the
Python wrapper):
```bash
# Ubuntu/Debian
sudo apt-get install -y tesseract-ocr
# macOS
brew install tesseract
```

### 2. Install Python deps
```bash
cd backend
pip install -r requirements.txt
```
This now includes `sentence-transformers` and `chromadb` — the first
install pulls in `torch`, so expect a larger download than earlier phases
(a few hundred MB).

### 3. Run
Same as Phase 3 — `.env` unchanged, just:
```bash
uvicorn main:app --reload --port 8000
```
On the **first** document you ingest, `sentence-transformers` downloads
its embedding model (`all-MiniLM-L6-v2`, ~80MB) from Hugging Face
automatically — this needs normal internet access once, then it's cached
locally and every ingestion after that is fully offline.

### 4. Try it
Open `frontend/index.html`, log in, click the 📎 icon, pick a PDF or
image. Review the extracted text in the card that appears, fix anything
OCR got wrong, click "Confirm & study this," then ask questions about it.

## What I verified directly (this sandbox has limited network access)
- ✅ `/extract` end-to-end through the real running server: uploaded a
  synthetic test image, got back OCR'd text with `needs_review: true`
- ✅ Text-based PDF extraction (no OCR triggered) — exact text back
- ✅ Chunking logic
- ✅ ChromaDB add / similarity search / delete — confirmed a query for
  "apple" correctly ranked apple-related chunks over an unrelated one
- ❌ Full `/documents` ingestion (which needs to download the embedding
  model from huggingface.co) and the vision fallback (needs
  generativelanguage.googleapis.com) — both blocked by this sandbox's
  network allow-list, not a problem with the code. Confirm these on your
  own machine with normal internet access; the failure mode you'd see
  here (`OSError: couldn't connect to huggingface.co`) is exactly that
  restriction, not a bug to chase.

## Known simplifications
- Retrieval always pulls top-4 chunks — no re-ranking, no minimum
  similarity threshold to say "this isn't in the document" more
  confidently (the prompt just asks the model to say so if the context
  doesn't answer it)
- One "active document" per conversation in the current frontend UI —
  the backend supports multiple documents per conversation
  (`GET /documents?conversation_id=`), the UI just doesn't expose
  switching between them yet
- Vision fallback only implemented for Gemini (the only adapter with a
  vision-capable endpoint wired up so far)

## Next step
Phase 5: the full admin panel UI (key CRUD, usage dashboard, user
management, analytics, moderation), plus the abuse-prevention and
security hardening items from the blueprint's risk list, and deployment.
