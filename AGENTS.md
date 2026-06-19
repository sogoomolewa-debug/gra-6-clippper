# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python automation pipeline for producing YouTube Shorts. The main orchestrator is `pipeline.py`; reusable stages live in `pipeline/` for search, queueing, heatmaps, transcripts, clip analysis, hooks, voice, editing, validation, and upload. Configuration is centralized in `config.py`.

Runtime state is stored in `data/` (`queue.json`, `performance_log.json`, `channel_analytics.json`). Static media and fonts belong in `assets/`. Generated or temporary media belongs in `scratch/` and should not be treated as source. Supporting scripts live in `scripts/`, documentation in `docs/`, and scheduled automation in `.github/workflows/`.

## Build, Test, and Development Commands

Create an environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the full pipeline locally in dry-run mode:

```bash
export DRY_RUN=true
python pipeline.py
```

Run the end-to-end rendering test:

```bash
python3 test_e2e.py
```

Useful module checks include `python3 -m pipeline.voice`, `python3 -m pipeline.hook`, `python3 -m pipeline.transcript "<youtube-url>" 45.0`, and `python3 -m pipeline.uploader`. Most require values from `.env`.

## Coding Style & Naming Conventions

Use idiomatic Python with 4-space indentation, descriptive snake_case names, and type hints where practical. Keep stages small and failure-tolerant: existing modules log errors and return safe defaults rather than crashing long-running jobs. Follow the bracketed log prefix style, for example `[search]` or `[pipeline]`.

Avoid unrelated refactors when changing a stage. Keep configuration in `config.py` or environment variables rather than hardcoding API keys, model names, paths, or channel settings.

## Testing Guidelines

Use `TESTING.md` as the manual verification checklist. `test_e2e.py` is the primary integration test for video composition, captions, audio, dimensions, and watermark behavior. Add focused tests or scripts when changing shared logic in `pipeline/`, especially scoring, queue mutations, clip boundaries, or editor output. Name tests `test_*.py`.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style prefixes such as `feat:`, `fix:`, and `chore:`. Keep commit subjects imperative and scoped to one logical change, for example `fix: handle missing transcript data`.

Pull requests should include a short summary, commands run, required environment variables or secrets, and before/after notes for generated media changes. Include screenshots or sample output paths when editing video layout, captions, branding, or assets.

## Security & Configuration Tips

Never commit live credentials. Keep local secrets in `.env` and document required keys in `.env.example`. Treat `client_secrets.json`, OAuth JSON, YouTube cookies, and API keys as sensitive. Prefer dry runs during development and verify `DRY_RUN` before testing uploader changes.
