.PHONY: setup check railway-check api web worker readiness eval-gates eval-replay eval-error-analysis arize-smoke eval-arize
ARIZE_SOFTWARE_REPORT ?= ../evals/results/gates.json
setup:
	cd backend && uv sync --group dev
	bash scripts/frontend-local.sh install
	bash scripts/frontend-local.sh railway-install
check:
	cd backend && uv run ruff check . ../examples
	cd backend && LOG_ONLY_ENABLED=false PAID_MODELS_ENABLED=false uv run pytest -q
	cd backend && uv run python -m unittest discover -s ../examples -p "test_*.py"
	bash scripts/frontend-local.sh typecheck
	bash scripts/frontend-local.sh build
	bash scripts/frontend-local.sh railway-check
railway-check:
	bash scripts/frontend-local.sh railway-check
api:
	cd backend && uv run uvicorn cfin.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
web:
	bash scripts/frontend-local.sh dev
worker:
	cd backend && PYTHONPATH=src uv run python -m cfin.worker
readiness:
	cd backend && PYTHONPATH=src uv run python -m cfin.readiness
eval-gates:
	cd backend && PYTHONPATH=src uv run python -m cfin.eval_runner --mode gates --output ../evals/results/gates.json
eval-replay:
	cd backend && PYTHONPATH=src uv run python -m cfin.eval_runner --mode replay --output ../evals/results/replay.json
eval-error-analysis:
	promptfoo eval -c evals/error-analysis-promptfoo.yaml --no-cache --no-progress-bar --output evals/results/error-analysis-policy-gates.json
arize-smoke:
	cd backend && PYTHONPATH=src uv run python -m cfin.arize_smoke --output ../evals/results/arize-auto-smoke.json
eval-arize:
	cd backend && PYTHONPATH=src uv run python -m cfin.arize_eval_cli --software-report "$(ARIZE_SOFTWARE_REPORT)" --experiment-name cfin-md01-software-gates --output ../evals/results/arize-gates.json
