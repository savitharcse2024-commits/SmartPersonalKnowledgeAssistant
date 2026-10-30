import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import streamlit as st

from database import create_backup, create_database, is_valid_backup, restore_backup
from knowledge import (
    DOCUMENT_IMPORT_ERRORS,
    MAX_UPLOAD_BYTES,
    STOP_WORDS,
    fts_expression,
    make_csv,
    make_summary,
    rank_passages,
    read_uploaded_document,
    search_terms,
    suggest_tags,
)


DATABASE_PATH = Path(__file__).parent / "knowledge.db"
PAGE_SIZE = 25
MAX_QUESTION_CANDIDATES = 1000
MAX_BATCH_FILES = 10
APP_IMPORT_ERRORS = DOCUMENT_IMPORT_ERRORS + (sqlite3.Error,)
create_database(DATABASE_PATH)


def _connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return closing(connection)


def _notes_where(search_text, tag_filter, source_filter, from_date, to_date):
    clauses = []
    parameters = []
    terms = search_terms(search_text)
    if terms:
        clauses.append("n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)")
        parameters.append(fts_expression(terms))
    elif search_text.strip():
        escaped = search_text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append(
            "(n.title LIKE ? ESCAPE '\\' OR n.content LIKE ? ESCAPE '\\' "
            "OR n.category LIKE ? ESCAPE '\\' OR n.tags LIKE ? ESCAPE '\\' "
            "OR n.source LIKE ? ESCAPE '\\')"
        )
        parameters.extend([f"%{escaped}%"] * 5)

    if tag_filter:
        clauses.append(
            "instr(',' || replace(lower(coalesce(n.tags, '')), ', ', ',') || ',', "
            "',' || lower(?) || ',') > 0"
        )
        parameters.append(tag_filter)
    if source_filter:
        clauses.append("n.source = ?")
        parameters.append(source_filter)
    if from_date:
        clauses.append("n.note_date >= ?")
        parameters.append(from_date.isoformat())
    if to_date:
        clauses.append("n.note_date <= ?")
        parameters.append(to_date.isoformat())

    return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters


def save_note(title, content, category, tags, note_date, source):
    with _connection() as connection:
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO notes (title, content, category, tags, note_date, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, content, category, tags, note_date, source),
            )
            return cursor.lastrowid


def get_notes(
    search_text="",
    tag_filter="",
    source_filter="",
    from_date=None,
    to_date=None,
    limit=PAGE_SIZE,
    offset=0,
):
    where, parameters = _notes_where(
        search_text, tag_filter, source_filter, from_date, to_date
    )
    with _connection() as connection:
        return connection.execute(
            """
            SELECT n.id, n.title, n.content, n.category, n.tags,
                   n.created_at, n.updated_at, n.note_date, n.source
            FROM notes n
            """
            + where
            + " ORDER BY n.note_date DESC, n.id DESC LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        ).fetchall()


def get_note_by_id(note_id):
    with _connection() as connection:
        return connection.execute(
            """
            SELECT id, title, content, category, tags,
                   created_at, updated_at, note_date, source
            FROM notes WHERE id = ?
            """,
            (note_id,),
        ).fetchone()


def count_notes(search_text="", tag_filter="", source_filter="", from_date=None, to_date=None):
    where, parameters = _notes_where(
        search_text, tag_filter, source_filter, from_date, to_date
    )
    with _connection() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM notes n" + where, parameters
        ).fetchone()[0]


def get_filter_options():
    with _connection() as connection:
        sources = [
            row[0] for row in connection.execute(
                "SELECT DISTINCT source FROM notes WHERE source <> '' ORDER BY source"
            )
        ]
        tag_rows = connection.execute("SELECT tags FROM notes WHERE tags <> ''").fetchall()
    tags = sorted({
        tag.strip()
        for row in tag_rows
        for tag in (row[0] or "").split(",")
        if tag.strip()
    }, key=str.casefold)
    return tags, sources


def update_note(note_id, title, content, category, tags, note_date, source):
    with _connection() as connection:
        with connection:
            connection.execute(
                """
                UPDATE notes
                SET title = ?, content = ?, category = ?, tags = ?,
                    note_date = ?, source = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, content, category, tags, note_date, source, note_id),
            )


def delete_note(note_id):
    with _connection() as connection:
        with connection:
            connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def make_database_backup():
    return create_backup(DATABASE_PATH)


def save_summary(note):
    note_id, title, content, category, tags, created_at, updated_at, note_date, source = note
    with _connection() as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO saved_summaries (note_id, note_title, source, note_date, summary)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note_id, title, source or "", note_date, make_summary(content)),
            )


def get_recent_summaries(limit=5):
    with _connection() as connection:
        return connection.execute(
            """
            SELECT id, note_id, note_title, source, note_date, summary, created_at
            FROM saved_summaries ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()


def find_duplicate_notes(current_id, title, content):
    exclusion = " AND id <> ?" if current_id is not None else ""
    parameters = [title, content]
    if current_id is not None:
        parameters.append(current_id)
    with _connection() as connection:
        return connection.execute(
            f"""
            SELECT id, title, source
            FROM notes
            WHERE (
                lower(trim(title)) = lower(trim(?))
                OR lower(trim(content)) = lower(trim(?))
            ){exclusion}
            ORDER BY id DESC LIMIT 5
            """,
            parameters,
        ).fetchall()


def find_duplicate_notes_for_page(notes):
    if not notes:
        return {}
    conditions = " OR ".join(
        "(lower(trim(title)) = lower(trim(?)) OR lower(trim(content)) = lower(trim(?)))"
        for _ in notes
    )
    parameters = [value for note in notes for value in (note[1], note[2])]
    with _connection() as connection:
        matches = connection.execute(
            f"""
            SELECT id, title, content, source
            FROM notes WHERE {conditions}
            ORDER BY id DESC LIMIT 500
            """,
            parameters,
        ).fetchall()

    duplicates_by_note = {}
    for note in notes:
        title_key = note[1].strip().casefold()
        content_key = note[2].strip().casefold()
        duplicates_by_note[note[0]] = [
            (match[0], match[1], match[3])
            for match in matches
            if match[0] != note[0]
            and (
                match[1].strip().casefold() == title_key
                or match[2].strip().casefold() == content_key
            )
        ][:5]
    return duplicates_by_note


def related_notes(note_id, content, limit=3):
    terms = [
        term for term in search_terms(content)
        if term not in STOP_WORDS and len(term) >= 3
    ]
    if not terms:
        return []
    expression = fts_expression(list(dict.fromkeys(terms[:8])))
    with _connection() as connection:
        return connection.execute(
            """
            SELECT n.id, n.title, n.source
            FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid
            WHERE notes_fts MATCH ? AND n.id <> ?
            ORDER BY bm25(notes_fts) LIMIT ?
            """,
            (expression, note_id, limit),
        ).fetchall()


def question_matches(question):
    keywords = [
        term for term in search_terms(question)
        if term not in STOP_WORDS and len(term) >= 2
    ]
    if not keywords:
        return [], 0

    expression = fts_expression(list(dict.fromkeys(keywords)))
    with _connection() as connection:
        candidates = connection.execute(
            """
            SELECT n.id, n.title, n.content, n.category, n.tags,
                   n.created_at, n.updated_at, n.note_date, n.source
            FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid
            WHERE notes_fts MATCH ?
            ORDER BY bm25(notes_fts) LIMIT ?
            """,
            (expression, MAX_QUESTION_CANDIDATES),
        ).fetchall()
        total = connection.execute(
            "SELECT COUNT(*) FROM notes_fts WHERE notes_fts MATCH ?",
            (expression,),
        ).fetchone()[0]

    results = []
    for note in candidates:
        ranked = rank_passages(note[2], keywords)
        if ranked:
            ranked.sort(key=lambda item: (-item[0], len(item[1])))
            results.append((ranked[0][0], note, ranked[0][1]))
    results.sort(
        key=lambda item: (
            -item[0],
            -date.fromisoformat(item[1][7]).toordinal(),
            -item[1][0],
        )
    )
    return results[:5], total


def reset_restore_confirmation():
    st.session_state["confirm_restore"] = False


def _display_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return date.today()


st.set_page_config(page_title="Smart Personal Knowledge Management Assistant")
st.title("Smart Personal Knowledge Management Assistant")
st.caption(
    "Local-first notes and documents. Keyword retrieval, summaries, and suggestions "
    "run offline; no note data is sent to an AI service."
)

requested_note_id = st.query_params.get("note_id")
if requested_note_id:
    try:
        linked_note = get_note_by_id(int(requested_note_id))
    except ValueError:
        linked_note = None
    if linked_note:
        st.subheader(f"Linked source note #{linked_note[0]}: {linked_note[1]}")
        st.caption(
            f"Date: {linked_note[7]} | Source: "
            f"{linked_note[8] or 'User-entered note'}"
        )
        st.write(linked_note[2])
    else:
        st.info("The linked source note is no longer available.")

with _connection() as connection:
    total_notes = connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
recent_notes = get_notes(limit=5)
recent_summaries = get_recent_summaries()
dashboard_col, summary_col = st.columns(2)
with dashboard_col:
    st.subheader("Dashboard: recent notes")
    st.metric("Saved notes", total_notes)
    if recent_notes:
        for note in recent_notes:
            st.link_button(
                f"Open note #{note[0]}: {note[1]}",
                url=f"?note_id={note[0]}",
                key=f"recent_note_{note[0]}",
            )
            st.caption(f"{note[7]} | {note[8] or 'User-entered'}")
    else:
        st.caption("No notes saved yet.")
with summary_col:
    st.subheader("Saved offline summaries")
    if recent_summaries:
        for summary in recent_summaries:
            st.caption(
                f"Source note #{summary[1] or 'deleted'}: {summary[2]} | "
                f"{summary[4]} | {summary[3] or 'User-entered'}"
            )
            if summary[1] is not None:
                st.link_button(
                    "Open summary source note",
                    url=f"?note_id={summary[1]}",
                    key=f"summary_source_{summary[0]}",
                )
            st.write(summary[5])
    else:
        st.caption("Save a note preview to show it here.")

st.header("Add a note")
with st.form("new_note_form"):
    title = st.text_input("Note title")
    content = st.text_area("Note content")
    category = st.text_input("Topic or project")
    tags = st.text_input("Tags (separate multiple tags with commas)")
    note_date = st.date_input("Note date", value=date.today())
    source = st.text_input("Source (for example, filename, URL label, or personal note)")
    submitted = st.form_submit_button("Save note")

if submitted:
    if title.strip() and content.strip():
        try:
            saved_id = save_note(
                title.strip(), content.strip(), category.strip(),
                ", ".join(tag.strip() for tag in tags.split(",") if tag.strip()),
                note_date.isoformat(), source.strip(),
            )
        except sqlite3.Error as error:
            st.error(f"Could not save this note: {error}")
        else:
            st.success("Note saved.")
            try:
                duplicates = find_duplicate_notes(saved_id, title, content)
            except sqlite3.Error as error:
                st.warning(f"The note was saved, but duplicate checking failed: {error}")
            else:
                if duplicates:
                    st.warning(
                        "Possible duplicate(s) to review: "
                        + ", ".join(f"#{item[0]} {item[1]}" for item in duplicates)
                    )
            st.rerun()
    else:
        st.error("Please enter both a title and note content.")

st.header("Import a document")
st.caption(
    "Import up to 10 approved TXT, text-based PDF, or DOCX files per batch. "
    "Each file may be up to 20 MB."
)
uploaded_files = st.file_uploader(
    "Choose documents",
    type=["txt", "pdf", "docx"],
    max_upload_size=MAX_UPLOAD_BYTES // (1024 * 1024),
    accept_multiple_files=True,
)
if uploaded_files and st.button("Import documents"):
    if len(uploaded_files) > MAX_BATCH_FILES:
        st.error(f"Select no more than {MAX_BATCH_FILES} files in one batch.")
    else:
        batch_progress = st.progress(0, text="Preparing local document import...")
        for index, uploaded_file in enumerate(uploaded_files):
            file_progress = st.progress(0, text=f"Reading {uploaded_file.name}...")
            try:
                with st.spinner(f"Extracting {uploaded_file.name} locally..."):
                    text = read_uploaded_document(uploaded_file, file_progress).strip()
            except APP_IMPORT_ERRORS as error:
                st.error(f"{uploaded_file.name}: could not import: {error}")
            else:
                if not text:
                    st.error(f"{uploaded_file.name}: no extractable text was found.")
                else:
                    imported_title = (
                        Path(uploaded_file.name).stem.strip() or "Imported document"
                    )
                    try:
                        saved_id = save_note(
                            imported_title,
                            text,
                            "Imported document",
                            Path(uploaded_file.name).suffix.lower().lstrip("."),
                            date.today().isoformat(),
                            uploaded_file.name,
                        )
                    except sqlite3.Error as error:
                        st.error(f"{uploaded_file.name}: text was extracted but not saved: {error}")
                    else:
                        st.success(f"{uploaded_file.name}: imported as a note.")
                        try:
                            duplicates = find_duplicate_notes(
                                saved_id, imported_title, text
                            )
                        except sqlite3.Error as error:
                            st.warning(
                                f"{uploaded_file.name} was saved, but duplicate "
                                f"checking failed: {error}"
                            )
                        else:
                            if duplicates:
                                st.warning(
                                    f"{uploaded_file.name} may duplicate: "
                                    + ", ".join(
                                        f"#{item[0]} {item[1]}" for item in duplicates
                                    )
                                )
            finally:
                file_progress.empty()
                batch_progress.progress(
                    (index + 1) / len(uploaded_files),
                    text=f"Processed {index + 1} of {len(uploaded_files)} files",
                )
        batch_progress.empty()

st.header("Find evidence in your notes")
st.caption(
    "Offline keyword retrieval returns matching source passages. It does not "
    "generate an answer or perform semantic search."
)
question = st.text_input("Ask a question or enter keywords")
if question.strip():
    matches, candidate_count = question_matches(question)
    if matches:
        if candidate_count > MAX_QUESTION_CANDIDATES:
            st.info("Showing the best passage matches from the first 1,000 indexed notes.")
        st.write(
            "Retrieved evidence only - it may not answer the whole question. "
            "Check the source note before relying on it."
        )
        for score, note, passage in matches:
            with st.expander(f"Source #{note[0]}: {note[1]}"):
                st.markdown(f"> {passage}")
                st.link_button(
                    "Open full source note",
                    url=f"?note_id={note[0]}",
                    key=f"question_source_{note[0]}",
                )
                st.caption(
                    f"Date: {note[7]} | Source: {note[8] or 'User-entered note'} | "
                    f"Topic: {note[3] or 'None'} | Tags: {note[4] or 'None'}"
                )
    else:
        st.info(
            "No saved passage matched these keywords. Your saved notes do not "
            "provide evidence for an answer to this query."
        )

st.header("Search and organize")
search_text = st.text_input("Search title, content, topic, tags, or source")
available_tags, available_sources = get_filter_options()
filter_cols = st.columns(4)
with filter_cols[0]:
    selected_tag = st.selectbox("Filter by tag", ["All tags", *available_tags])
with filter_cols[1]:
    selected_source = st.selectbox("Filter by source", ["All sources", *available_sources])
with filter_cols[2]:
    from_date = st.date_input("From date", value=None, key="filter_from_date")
with filter_cols[3]:
    to_date = st.date_input("To date", value=None, key="filter_to_date")
tag_filter = "" if selected_tag == "All tags" else selected_tag
source_filter = "" if selected_source == "All sources" else selected_source

if from_date and to_date and from_date > to_date:
    st.error("The start date must be on or before the end date.")
    filtered_count = 0
    notes = []
else:
    filtered_count = count_notes(
        search_text, tag_filter, source_filter, from_date, to_date
    )
    total_pages = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page_options = list(range(1, total_pages + 1))
    page_key = (
        f"note_page_{hash((search_text, tag_filter, source_filter, from_date, to_date))}"
    )
    if st.session_state.get(page_key) not in page_options:
        st.session_state[page_key] = 1
    page = st.selectbox(
        f"Page (25 records per page; {filtered_count} matching)",
        options=page_options,
        key=page_key,
    )
    notes = get_notes(
        search_text,
        tag_filter,
        source_filter,
        from_date,
        to_date,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )

st.subheader("Export records")
if notes:
    st.download_button(
        "Export current page as CSV",
        data=make_csv(notes),
        file_name="knowledge_notes_page.csv",
        mime="text/csv",
    )
    selected_records = [
        note for note in notes
        if st.checkbox(f"Select for export: #{note[0]} {note[1]}", key=f"export_{note[0]}")
    ]
    if selected_records:
        st.download_button(
            "Export selected records as CSV",
            data=make_csv(selected_records),
            file_name="knowledge_notes_selected.csv",
            mime="text/csv",
        )
else:
    st.caption("No matching notes to export.")

st.header("Notes")
if not notes:
    st.info("No matching notes found.")

page_duplicates = find_duplicate_notes_for_page(notes)
for note in notes:
    note_id, note_title, note_content, note_category, note_tags, created_at, updated_at, saved_date, note_source = note
    with st.expander(f"{note_title} (#{note_id})"):
        st.write(note_content)
        st.caption(f"Topic/project: {note_category or 'None'}")
        st.caption(f"Tags: {note_tags or 'None'}")
        st.caption(f"Note date: {saved_date} | Source: {note_source or 'User-entered note'}")
        st.caption(f"Created: {created_at} | Updated: {updated_at}")

        st.subheader("Simple offline summary hint")
        st.caption("First-sentences preview, not an AI-generated summary.")
        st.write(make_summary(note_content))
        if st.button("Save this summary preview", key=f"save_summary_{note_id}"):
            try:
                save_summary(note)
            except sqlite3.Error as error:
                st.error(f"Could not save this summary preview: {error}")
            else:
                st.success("Summary preview saved with its note title, date, and source.")
                st.rerun()

        suggestions = suggest_tags(note_content, note_tags)
        if suggestions and not st.session_state.get(f"tags_dismissed_{note_id}", False):
            st.subheader("Offline tag suggestions")
            st.caption("Review, edit, and select suggestions to add; nothing is applied automatically.")
            selected_suggestions = st.multiselect(
                "Suggested tags",
                suggestions,
                key=f"tag_suggestions_{note_id}",
                accept_new_options=True,
            )
            accept_col, reject_col = st.columns(2)
            with accept_col:
                if st.button("Add selected tags", key=f"accept_tags_{note_id}"):
                    existing = [
                        tag.strip() for tag in (note_tags or "").split(",") if tag.strip()
                    ]
                    combined = existing + [
                        tag for tag in selected_suggestions
                        if tag.casefold() not in {item.casefold() for item in existing}
                    ]
                    try:
                        update_note(
                            note_id, note_title, note_content, note_category or "",
                            ", ".join(combined), saved_date, note_source or "",
                        )
                    except sqlite3.Error as error:
                        st.error(f"Could not update tags: {error}")
                    else:
                        st.success("Selected tags added.")
                        st.rerun()
            with reject_col:
                if st.button("Dismiss tag suggestions", key=f"reject_tags_{note_id}"):
                    st.session_state[f"tags_dismissed_{note_id}"] = True
                    st.rerun()

        duplicates = page_duplicates.get(note_id, [])
        st.subheader("Possible duplicates")
        if duplicates:
            st.caption("Exact title or content matches; review them without automatic deletion.")
            for duplicate_id, duplicate_title, duplicate_source in duplicates:
                st.write(
                    f"Source #{duplicate_id}: {duplicate_title} "
                    f"({duplicate_source or 'User-entered note'})"
                )
        else:
            st.caption("No exact title or content duplicates detected.")

        st.subheader("Offline related-note hints")
        st.caption("Based on shared indexed words, not semantic similarity.")
        related = related_notes(note_id, f"{note_title} {note_content}")
        if related:
            for related_id, related_title, related_source in related:
                st.link_button(
                    f"Open related note #{related_id}: {related_title}",
                    url=f"?note_id={related_id}",
                    key=f"related_source_{note_id}_{related_id}",
                )
        else:
            st.caption("No related notes found.")

        with st.form(f"edit_note_form_{note_id}"):
            new_title = st.text_input("Title", value=note_title, key=f"title_{note_id}")
            new_content = st.text_area("Content", value=note_content, key=f"content_{note_id}")
            new_category = st.text_input(
                "Topic or project", value=note_category or "", key=f"category_{note_id}"
            )
            new_tags = st.text_input("Tags", value=note_tags or "", key=f"tags_{note_id}")
            new_date = st.date_input(
                "Note date", value=_display_date(saved_date), key=f"date_{note_id}"
            )
            new_source = st.text_input(
                "Source", value=note_source or "", key=f"source_{note_id}"
            )
            save_changes = st.form_submit_button("Save changes")
            delete_this_note = st.form_submit_button("Delete note")

        if save_changes:
            if new_title.strip() and new_content.strip():
                try:
                    update_note(
                        note_id, new_title.strip(), new_content.strip(),
                        new_category.strip(),
                        ", ".join(tag.strip() for tag in new_tags.split(",") if tag.strip()),
                        new_date.isoformat(), new_source.strip(),
                    )
                except sqlite3.Error as error:
                    st.error(f"Could not update this note: {error}")
                else:
                    st.success("Note updated.")
                    st.rerun()
            else:
                st.error("Title and content cannot be empty.")

        if delete_this_note:
            st.session_state[f"confirm_delete_{note_id}"] = True
            st.rerun()

        if st.session_state.get(f"confirm_delete_{note_id}", False):
            st.warning(f"Delete '{note_title}'? This permanently removes this note.")
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button("Confirm delete", key=f"confirm_delete_button_{note_id}"):
                    try:
                        delete_note(note_id)
                    except sqlite3.Error as error:
                        st.error(f"Could not delete this note: {error}")
                    else:
                        st.session_state.pop(f"confirm_delete_{note_id}", None)
                        st.success("Note deleted.")
                        st.rerun()
            with cancel_col:
                if st.button("Cancel deletion", key=f"cancel_delete_{note_id}"):
                    st.session_state.pop(f"confirm_delete_{note_id}", None)
                    st.rerun()

st.header("Export and restore")
st.download_button(
    "Download full SQLite database backup",
    data=make_database_backup(),
    file_name="knowledge_backup.db",
    mime="application/octet-stream",
)
st.warning(
    "Restoring replaces all notes and saved data in the current database. "
    "Download a backup first; select a backup you have checked before continuing."
)
backup_file = st.file_uploader(
    "Choose a knowledge database backup",
    type=["db"],
    key="backup_uploader",
    on_change=reset_restore_confirmation,
)
if backup_file is not None:
    confirm_restore = st.checkbox(
        "I understand this replaces the current database.",
        key="confirm_restore",
    )
    if st.button("Restore database", disabled=not confirm_restore):
        backup_bytes = backup_file.getvalue()
        if is_valid_backup(backup_bytes):
            try:
                restore_backup(backup_bytes, DATABASE_PATH)
            except (OSError, sqlite3.Error) as error:
                st.error(f"Could not restore this backup: {error}")
            else:
                st.success("Database restored.")
                st.rerun()
        else:
            st.error("This backup is invalid or does not contain a supported notes table.")
