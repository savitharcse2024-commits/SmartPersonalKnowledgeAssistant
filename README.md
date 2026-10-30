# Smart Personal Knowledge Management Assistant

A local-first personal notes and document app. Notes and saved summary previews
are stored in the project folder's `knowledge.db` SQLite database.

## Features

- Add and edit notes with title, topic/project, tags, note date, and source.
- Batch-import up to 10 approved TXT, text-based PDF, and DOCX documents
  (including DOCX table text); the original file name is recorded as the source.
- Confirm before deleting a note. Saved summaries for that note are deleted too.
- Detect exact title/content duplicates and suggest shared-word related notes;
  suggestions never delete or change content automatically.
- Search title, content, topic, tags, and source using a local SQLite FTS5 index.
  Filter by date range, tag, and source; results are paginated.
- Retrieve matching note passages for a question and cite note ID, date, and
  source. If no passage matches, the app says the saved notes provide no evidence.
- Show a first-sentences offline preview, frequent-word tag suggestions, and
  shared-word related-note hints. Users can edit/select or dismiss tag suggestions.
- Save summary previews with their source note details, and view recent notes and
  saved previews on the dashboard.
- Export the current page or selected records to CSV; download a full SQLite
  backup and restore a validated backup after a warning and explicit confirmation.

## Honest limitations

Question handling is keyword-based retrieval, not semantic search, and it does
not compose an answer. Summaries are first-sentence previews, not AI-generated
summaries. Tag, duplicate, and related-note suggestions use simple local rules.
PDF import extracts embedded text only; scanned-image OCR is not included.
Each imported file is limited to 20 MB and each batch to 10 files. Use documents
you are authorized to store.

There is no external AI/LLM integration and the app does not send note data to
an external service. Semantic embeddings and AI-generated answers are
intentionally not implemented; connecting an external model would require a
separate approved privacy decision.

## Requirements and compatibility

- Python 3.12
- SQLite with FTS5 enabled (bundled with the tested Python distribution)
- Dependency versions pinned in `requirements.txt`
- Windows 10/11 is the validated target. The app uses Python and Streamlit and
  may run on macOS/Linux, but those operating systems have not been validated
  for this project.
- Use a current browser that supports JavaScript (for example, Chrome, Edge, or
  Firefox). The app is served locally; browser compatibility outside the local
  development environment has not been independently tested.

Tested runtime: Python 3.12.10, SQLite 3.49.1, Streamlit 1.64.0, PyMuPDF 2.0,
and python-docx 1.2.0.

## Setup and run on Windows

Open PowerShell in this project folder:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Open `http://127.0.0.1:8501` in your browser. Stop the app with **Ctrl+C** in
PowerShell. Binding to `127.0.0.1` keeps the Streamlit server on this computer.

## Database migration, backup, and recovery

On startup, the app adds missing date/source fields and search indexes to a
compatible older notes schema without deleting note rows. Keep a backup before
running a new version. The FTS5 index can be rebuilt from saved notes; it is a
search aid, not the only copy of note content.

Use **Download full SQLite database backup** before upgrades or restores. If an
import is interrupted before the note is saved, the original database remains
unchanged; select the file and retry. If a database becomes unavailable or
corrupt, stop the app with **Ctrl+C**, keep a copy of the affected database for
recovery, restart the app, and restore a previously downloaded valid backup.
Restoring replaces the current database; the UI warns and requires confirmation.
Never overwrite the only copy of a backup.

Run the automated offline tests with:

```powershell
python -m unittest discover -s tests -v
```

## Project modules

- `app.py`: Streamlit interface and database-backed workflows.
- `database.py`: schema migration, SQLite FTS5 index, integrity checks, and backup/restore.
- `knowledge.py`: local document extraction, CSV formatting, previews, and
  keyword/tag heuristics.
