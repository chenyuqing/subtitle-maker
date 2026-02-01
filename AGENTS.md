# Repository Guidelines

## Project Structure & Module Organization
- `src/subtitle_maker/` houses the FastAPI app: `web.py` orchestrates routing/background work, `transcriber.py` wraps Qwen3-ASR, `translator.py` connects to DeepSeek/Sakura, and `cli.py` exposes the console entry point.
- Templates and static assets live in `src/subtitle_maker/templates` and `src/subtitle_maker/static`; colocate page-specific JS/CSS with its template.
- Long-lived artifacts: `models/` (downloaded weights), `uploads/` (ingested media), `outputs/` (exported `.srt`).
- Operational helpers (`start.sh`, `stop.sh`, `start_local_model.sh`) live at the project root with sample media/tests.

## Build, Test, and Development Commands
- `uv sync` – install Python dependencies pinned by `pyproject.toml` and `uv.lock`.
- `uv run subtitle-maker-web` – start the API server on port 8000; `./start.sh` wraps the same command with dependency checks, port cleanup, and browser launch.
- `./start_local_model.sh` – boot the llama.cpp Sakura model on port 8081; monitor `llama_server.log` for load status.
- `./stop.sh` – kill FastAPI and llama-server processes, clearing ports 8000/8081.
- `uv run python test_local_sakura.py` – smoke-test the Sakura endpoint before enabling translation in the UI.

## Coding Style & Naming Conventions
- Target Python 3.10+, 4-space indents, PEP 8 naming (snake_case for functions/vars, CapWords for classes such as `SakuraManager`).
- Prefer explicit type hints, descriptive logging (`logger.info("Transcribing %s", file_path)`), and small async helpers.
- Keep route names, template IDs, and fetch URLs aligned (`/upload` ↔ `upload_video`). 

## Testing Guidelines
- Grow coverage by adding `tests/` modules mirroring the file under test (`test_web.py` for `web.py`) and running them with `uv run pytest`.
- Extend `test_local_sakura.py` to verify connectivity, latency, and error messaging; skip network-dependent cases when the model server is absent.
- Use lightweight media clips under `uploads/` and assert that generated `.srt` artifacts land in `outputs/` with expected timestamps/text.

## Commit & Pull Request Guidelines
- Write imperative, scoped commit messages (`feat: add bilingual overlay toggle`) with an optional body listing motivations and commands executed.
- PRs must include a concise summary, screenshots when altering the overlay preview, linked issues, and a `Test Plan` that names each command (e.g., `uv run subtitle-maker-web`).
- Highlight new dependencies, model assets, or environment variables so reviewers can replicate your setup.

## Security & Configuration Tips
- Keep API keys out of Git; load DeepSeek/OpenAI credentials via environment variables or user prompts, and ensure `.env` stays ignored.
- Do not commit large binaries from `models/`, `uploads/`, or `outputs/`; instead, document download steps and scrub demo clips for PII.
