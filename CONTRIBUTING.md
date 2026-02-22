# Contributing to Vanguard

Thanks for your interest in contributing.

## Development setup
1. Fork and clone the repository.
2. Run:
   ```bash
   ./scripts/setup_env.sh
   ```
3. Configure `.env` from `.env.example`.

## Local checks
Run these before opening a PR:
```bash
PYTHONPATH=src pytest -q
python -m src.vanguard.health --check-only
```

## Pull request guidelines
- Keep PRs focused and small.
- Add/adjust tests when behavior changes.
- Update README/docs for any operator-facing changes.
- Do not commit secrets or `.env`.

## Commit style
- Use clear, imperative commit messages.
- Example: `Add Ollama health check for startup preflight`
