# AGENTS.md

Guidance for coding agents working in this repository.

## Project Overview

`ascend-ci-insight` collects and analyzes vllm-ascend CI failures, classifies pipeline health, writes static dashboard data under `docs/`, and can notify on alerts. The command entry point is:

```bash
python -m src
```

The console script defined in `pyproject.toml` is:

```bash
ascend
```

## Repository Layout

- `src/`: Python implementation for collection, analysis, reporting, health scoring, alerts, notifications, interference detection, and aggregation.
- `tests/`: pytest suite and shared fixtures.
- `config/rules.json`: source of truth for pipeline/category classification rules.
- `docs/`: static dashboard assets plus generated JSON reports.
- `docs/rules.json`: dashboard copy of `config/rules.json`; keep it in sync.
- `specs/`: design notes and behavioral specs for agents and maintainers.
- `scripts/run.sh`: authenticated end-to-end run wrapper.
- `scripts/verify.sh`: pre-commit verification checklist.

## Environment Assumptions

- Python `>=3.10`.
- `gh` CLI is required for live GitHub data collection and must be authenticated.
- `claude` CLI is required for normal analysis runs unless using modes that skip analysis.
- The project currently has a minimal dependency set in `pyproject.toml`; do not add dependencies casually.

## Common Commands

Install editable package:

```bash
python -m pip install -e .
```

Run tests:

```bash
python -m pytest tests/ -q
```

Run the full local verification script on Unix-like shells:

```bash
./scripts/verify.sh
```

Run analysis:

```bash
python -m src --days 7 --limit 30 --lang en
```

Analyze a single PR:

```bash
python -m src --pr 9495 --lang en
```

Recompute health, alerts, interference, and snapshots from existing reports:

```bash
python -m src --health
```

Rebuild local SQLite from committed static dashboard JSON:

```bash
python -m src --import-static
```

Collect only, skipping Claude analysis:

```bash
python -m src --no-analyze
```

## Development Rules

- Keep changes small and aligned with the existing simple module layout.
- Prefer standard library code unless a dependency already exists or the benefit is clear.
- Preserve JSON schemas consumed by the dashboard unless updating all readers and fixtures at the same time.
- Keep generated dashboard data deterministic where possible so diffs remain reviewable.
- Do not overwrite or delete existing reports under `docs/reports/` unless the task explicitly asks for data regeneration or cleanup.
- When changing classification behavior, update `config/rules.json` first and then sync `docs/rules.json`.
- When changing data models in `src/models.py`, inspect reporter, health, alert, interference, aggregator, and tests for serialization assumptions.
- Keep user-facing output language behavior in mind: the CLI accepts `--lang zh` and `--lang en`.

## Rule Sync Requirement

`config/rules.json` is the canonical rule file. The dashboard reads `docs/rules.json`.

After modifying rules, run:

```bash
cp config/rules.json docs/rules.json
```

On Windows PowerShell:

```powershell
Copy-Item config\rules.json docs\rules.json
```

Then run:

```bash
python -m pytest tests/ -q
```

## Testing Guidance

- For logic-only changes, run the focused test file plus the full suite if practical.
- For rules or classifier changes, run all classifier, health, alert, and data-integrity tests.
- For dashboard JSON/report changes, inspect representative files under `docs/reports/` and ensure `docs/index.html` still loads the expected JSON paths.
- `scripts/verify.sh` expects existing reports to be loadable and checks rule sync, health computation, and whitespace.

## Live Data Safety

Live collection depends on GitHub API state and may be slow or rate-limited. Prefer cached-report workflows for local iteration:

```bash
python -m src --health --no-notify
```

Use live collection only when the task needs current GitHub data:

```bash
python -m src --days 1 --limit 5 --no-analyze --no-notify
```

## Generated Artifacts

The tool writes reports, indexes, health summaries, alerts, interference data, and snapshots. Before committing, check which generated files changed and confirm they are relevant to the task:

```bash
git status --short
```

Do not include incidental report churn in code-only changes.

## Live Data Collection Workflow

When collecting live CI data or running AI analysis that produces generated artifacts under `docs/reports/`, work in an isolated branch and worktree to avoid polluting `main`:

```bash
# 1. Create a branch for the data refresh
git checkout -b data/refresh-YYYY-MM-DD

# 2. Run collection/analysis (in worktree or directly)
python -m src --days 1 --limit 10 --lang zh

# 3. Commit generated artifacts
git add docs/reports/ docs/index.html docs/app.js docs/health.js docs/i18n.js docs/style.css
git commit -m "Refresh CI data and analysis for YYYY-MM-DD"

# 4. Push and create PR
git push -u origin HEAD
gh pr create --title "Refresh CI data for YYYY-MM-DD" --body "Automated data refresh."

# 5. After PR is merged, switch back to main and pull
git checkout main
git pull
```

- Always use a dedicated branch for data refreshes — never commit generated reports directly to `main`.
- Prefer `--days 1 --limit 10` for quick daily refreshes; use `--days 7 --limit 30` for weekly deep dives.
- Verify `python -m pytest tests/ -q` passes before pushing.
- Use `gh pr view --web` to review the PR diff before merging.
