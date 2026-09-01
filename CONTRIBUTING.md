# Contributing to InternApply

Thanks for considering a contribution. This project follows a standard fork and PR flow.

## Quick start

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/internapply.git
cd internapply

# 2. Create a branch
git checkout -b feat/your-feature

# 3. Install dev deps
pip install -e ".[dev]"

# 4. Make changes, then test
pytest -q
ruff check .

# 5. Commit and push
git commit -m "feat: your feature"
git push origin feat/your-feature
```

Then open a PR against `main`.

## Guidelines

- Keep PRs focused, one feature per PR.
- Add tests for new logic (verifier, hash, pipeline, discovery).
- Do not add secrets or API keys, use `.env.example` placeholders.
- Run `ruff` and `pytest` before pushing, CI must stay green.
- For discovery changes, test with `--dry-run` first.

## What to work on

See open issues for `good first issue` labels. For larger changes, open an issue first to discuss approach.

## Questions

Open an issue or start a discussion on GitHub. Also see [README.md](README.md#contributing) for the same flow in brief.
