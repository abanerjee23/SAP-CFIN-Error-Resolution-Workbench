# Local development

## Frontend preview

From the project folder, run:

```bash
bash scripts/frontend-local.sh install
bash scripts/frontend-local.sh dev
```

Open http://127.0.0.1:3000. Keep the terminal running; Ctrl+C stops the preview. The launcher uses Node 22.23.3, pinned in `frontend/.nvmrc`. On Apple Silicon Macs it keeps the checksum-verified Node runtime, locked dependencies and Next.js output in a project-specific OS temporary directory, linked from `frontend/node_modules` and `frontend/.next`. This prevents iCloud from offloading runtime files in the Documents folder and stalling startup. It uses Webpack for these externally linked dependencies. Missing temporary files are restored automatically; the first run or a changed dependency lock requires internet access. `CFIN_FRONTEND_LOCAL_DIR` can select another local, unsynced directory. Other machines can use their own Node 22 installation. Run `bash scripts/frontend-local.sh typecheck` and `bash scripts/frontend-local.sh build` for software checks.

## Setup and checks

Use Python 3.11+ with `uv` and Node 22. Set up locked dependencies and run the standard checks:

```bash
make setup
make check
```

`make check` runs Python lint, backend regression tests, example-client tests, frontend typechecking, an optimized frontend build and offline Railway configuration validation. GitHub Actions runs the corresponding checks plus executable database verification. To exercise migrations and transaction guards locally, use a disposable pgvector/PostgreSQL container:

```bash
docker run --detach --rm --name cfin-verification \
  -e POSTGRES_PASSWORD=cfin-local-only pgvector/pgvector:0.8.6-pg17
cd backend
CFIN_POSTGRES_CONTAINER=cfin-verification LOG_ONLY_ENABLED=false \
  PAID_MODELS_ENABLED=false uv run pytest -q tests/test_log_only_migration.py
cd ..
docker stop cfin-verification
```

The zero-cost Error Analysis policy suite runs with `make eval-error-analysis` when Promptfoo is installed. Local `.env` files, dependencies, caches and evaluation outputs are excluded from Git. Copy the checked-in `.env.example` files when configuring a new environment. A copied Python virtual environment must be recreated with `uv sync --locked --group dev`, because its executable paths can refer to the previous folder. See the [repository validation record](repository-validation.md) for checks run before the initial push and their limits.

## Document changes

Keep the README focused on the product overview. Put detailed product rules in `docs/product-design.md` and interface rules in `docs/FRONTEND_DESIGN.md`. Record implemented enhancements in `enhancements/enhancement_DDMMYYYY.md`, using the Europe/London implementation date. Append to the existing file for that date and include the reason, changes, validation and limitations.
