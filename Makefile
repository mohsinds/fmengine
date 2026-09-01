.PHONY: up down logs install check check-integration health resources \
	ingest features sweep backtest worker campaign pause resume ui

UV ?= uv
COMPOSE ?= docker compose

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

install:
	# Core deps from [project].dependencies; tooling from [dependency-groups].dev
	$(UV) sync --group dev

check:
	$(UV) run ruff format --check src tests
	$(UV) run ruff check src tests
	$(UV) run mypy
	$(UV) run pytest

check-integration:
	$(UV) run pytest -m integration

health:
	$(UV) run fmtrader system health

resources:
	$(UV) run fmtrader system resources

ingest:
	$(UV) run fmtrader data ingest \
		--adapter dukascopy \
		--path download/xauusd-m1-bid-2021-01-01-2026-08-31.csv \
		--symbol XAUUSD \
		--timeframe 1m \
		--instrument-class spot_cfd \
		--side bid

features:
	$(UV) run fmtrader features build \
		--dataset xauusd_1m_bid_2021-01-03_2026-08-30 \
		--set configs/features/baseline.yaml

sweep:
	$(error Phase 4 not implemented yet — see SETUP_PROMPT.md)

backtest:
	$(error Phase 4 not implemented yet — see SETUP_PROMPT.md)

worker:
	$(error Phase 7 not implemented yet — see SETUP_PROMPT.md)

campaign:
	$(error Phase 7 not implemented yet — see SETUP_PROMPT.md)

pause:
	$(error Phase 7 not implemented yet — see SETUP_PROMPT.md)

resume:
	$(error Phase 7 not implemented yet — see SETUP_PROMPT.md)

ui:
	$(error Phase 11 not implemented yet — see FRONTEND_SPEC.md)
