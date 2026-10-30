# Smart Personal Knowledge Management Assistant

## Project overview

This local-first Python and Streamlit app organizes personal notes and approved
documents in SQLite. It indexes content for local keyword retrieval, displays
source passages, and provides simple offline previews and suggestions.

## Objectives and delivered functionality

1. **Create and organize records:** Notes store title, topic/project, user-defined
   tags, a note date, a source label, creation time, and last-updated time.
2. **Import documents:** Batch-extract text from up to 10 TXT, text-based PDF,
   and DOCX files (paragraphs and tables); record the filename as the source.
   Each file is limited to 20 MB, malformed/unsupported files show an error, and
   a failed file does not stop the rest of the batch. Scanned PDF OCR is not
   provided.
3. **Search index and filters:** SQLite FTS5 indexes title, content, topic,
   tags, and source. Search results are paginated and can be filtered by date,
   tag, or source.
4. **Source-grounded lookup:** Question keywords retrieve matching passages
   from saved note content and show note ID, date, and source. When no passage
   matches, the app states that saved notes do not provide evidence. It does
   not invent an answer.
5. **Summaries and relationships:** The first-sentences preview, frequent-word
   tag recommendations, exact duplicate hints, and shared-word related-note
   hints are deterministic offline heuristics. Users can select/edit or dismiss
   tag suggestions. Duplicate and related hints never delete content.
6. **Dashboard:** Shows recent notes and saved offline preview snapshots with
   their source note references.
7. **Export and recovery:** Export the current page or selected records to CSV;
   create a complete SQLite backup; validate a backup before restore and require
   explicit confirmation because restore replaces current database contents.
8. **Deletion:** Confirm before deleting an individual note. Its saved summary
   snapshots are removed with it.

## Architecture and technology

- `app.py`: Streamlit UI, filters, pagination, and workflows.
- `database.py`: SQLite schema migration, indexes, FTS5 maintenance, and backup
  validation/restore.
- `knowledge.py`: local file extraction, CSV generation, first-sentence
  previews, and keyword/tag processing.
- Python 3.12, Streamlit, SQLite FTS5, PyMuPDF, and python-docx.

## Privacy and responsible use

The app binds to `127.0.0.1` in the documented run command. Notes and processing
remain on the local computer; no external AI service is used and note data is
not sent to an internet service. Import only documents you are authorized to
store. Search results provide source evidence for human review; they are not
guaranteed answers or high-impact recommendations.

Semantic embeddings and AI-generated answers are not implemented. Search is
keyword-based, summaries are previews rather than generated summaries, and
recommendations are simple heuristics. This avoids implying model capabilities
or sending private data to an unapproved service.

## Performance, reliability, and recovery

FTS5 supports indexed keyword lookup. Date and source indexes, pagination,
bounded question candidates, a 10-file batch limit, and a 20 MB per-file limit
bound common workloads. PDF extraction displays page progress. Each import is
saved only after text extraction succeeds. SQLite backup/restore APIs, backup integrity validation,
and an explicit restore warning support recovery. Keep a separate backup before
upgrading or restoring; see `README.md` for recovery steps.

## Compatibility and setup

Validated in the current workspace on Windows with Python 3.12.10, SQLite
3.49.1, Streamlit 1.64.0, PyMuPDF 2.0, and python-docx 1.2.0. A modern
JavaScript-enabled browser is required. macOS/Linux and browser combinations
outside the local workspace have not been independently tested.

Install and run from PowerShell in the project folder:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Run offline automated checks with:

```powershell
python -m unittest discover -s tests -v
```

## Known scope gaps

The college brief lists optional semantic retrieval and an approved LLM adapter.
Neither is enabled: the agreed privacy requirement is to keep note processing
offline and avoid external AI/data transfer. The app therefore returns
keyword-matched source passages instead of AI-generated natural-language
answers. A future AI integration would require explicit institutional approval,
privacy review, and user consent before implementation.

The provided working folder is not configured as a Git repository and has no
GitHub remote. No remote repository or credentials were created as part of this
local application work.
