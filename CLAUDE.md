# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses `uv` for dependency management and execution (Python 3.13+, see `.python-version`). Always use `uv` — `uv sync` to install, `uv run ...` to run any Python file or script — never call `pip` or bare `python` directly.

```bash
# Install dependencies
uv sync

# Run the server (from backend/, with auto-reload)
cd backend && uv run uvicorn app:app --reload --port 8000

# Run any other Python file
uv run python <file.py>

# Or use the helper script (Git Bash on Windows)
./run.sh
```

No test suite, linter, or formatter is currently configured in this repo.

Environment: requires a `.env` file in the project root with `ANTHROPIC_API_KEY=...` (see `.env.example`).

Once running: web UI at `http://localhost:8000`, Swagger docs at `http://localhost:8000/docs`.

## Architecture

This is a RAG (Retrieval-Augmented Generation) chatbot that answers questions about course materials. Vanilla JS/HTML/CSS frontend, FastAPI backend, ChromaDB for vector storage, Claude for generation.

```
frontend (static JS/HTML/CSS)  →  FastAPI (app.py)  →  RAGSystem (rag_system.py)
                                                          ├── DocumentProcessor   — parses course docs into chunks
                                                          ├── VectorStore         — ChromaDB wrapper (2 collections)
                                                          ├── AIGenerator         — Claude API + tool-use loop
                                                          ├── SessionManager      — in-memory conversation history
                                                          └── ToolManager / CourseSearchTool
```

All backend code lives flat in `backend/` (no subpackages): `app.py`, `rag_system.py`, `document_processor.py`, `vector_store.py`, `ai_generator.py`, `search_tools.py`, `session_manager.py`, `models.py`, `config.py`.

### Query flow

1. Frontend (`frontend/script.js`) POSTs `{query, session_id}` to `/api/query`.
2. `RAGSystem.query()` builds a prompt, loads conversation history from `SessionManager`, and calls `AIGenerator.generate_response()` with the `search_course_content` tool definition attached.
3. `AIGenerator` makes a first call to Claude with `tools` + `tool_choice: auto`. Claude either answers directly (general knowledge) or requests the search tool (course-specific questions), per the system prompt in `ai_generator.py`.
4. If Claude requests a search: `ToolManager` executes `CourseSearchTool`, which calls `VectorStore.search()` — this resolves a fuzzy `course_name` against the `course_catalog` collection first, then queries the `course_content` collection with an optional course/lesson filter.
5. Tool results are fed back to Claude in a **second** API call that omits the `tools` param — this is the actual mechanism capping a query at one search round (not just a prompt instruction).
6. `RAGSystem` collects sources off `CourseSearchTool.last_sources` (a side-channel — sources aren't returned directly from the search call), resets them, and appends the exchange to session history.
7. Response returns as `{answer, sources, session_id}` and the frontend renders the answer as markdown with a collapsible sources panel.

### Document ingestion

On FastAPI startup, `app.py` calls `RAGSystem.add_course_folder("../docs")`, which processes every `.pdf/.docx/.txt` file, skipping courses whose title already exists in `course_catalog` (so restarts don't re-embed).

Expected document format (`document_processor.py`):
```
Course Title: <title>
Course Link: <url>
Course Instructor: <name>

Lesson 0: <title>
Lesson Link: <url>
<lesson content...>

Lesson 1: <title>
...
```

`DocumentProcessor.chunk_text()` splits each lesson into sentence-aware chunks (`CHUNK_SIZE`/`CHUNK_OVERLAP` from `config.py`) with overlap carried between chunks for context continuity. Chunks are stored in ChromaDB's `course_content` collection; course/lesson metadata (including a JSON-serialized lesson list) goes into `course_catalog`, embedded with `all-MiniLM-L6-v2`.

### Key config (`backend/config.py`)

- `ANTHROPIC_MODEL`, `EMBEDDING_MODEL`
- `CHUNK_SIZE` / `CHUNK_OVERLAP` — document chunking
- `MAX_RESULTS` — search results returned per query
- `MAX_HISTORY` — conversation exchanges retained per session
- `CHROMA_PATH` — local ChromaDB storage path

### State and persistence notes

- Session history lives in an in-memory dict on `SessionManager` — lost on server restart.
- ChromaDB is persisted locally at `CHROMA_PATH`, so ingested course content survives restarts (re-ingestion is skipped for existing course titles).
