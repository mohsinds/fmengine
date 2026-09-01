.PHONY: up down logs install check check-integration health resources \
	ingest features sweep backtest validate noise-calibration worker campaign pause resume ui

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
	$(UV) run fmtrader backtest sweep \
		--strategy ema_cross \
		--space configs/spaces/ema_cross.yaml \
		--dataset xauusd_1m_bid_2021-01-03_2026-08-30 \
		--max 200 \
		--workers 6

backtest:
	$(UV) run fmtrader backtest run \
		--strategy buy_and_hold \
		--params configs/strategies/buy_and_hold.yaml \
		--dataset xauusd_1m_bid_2021-01-03_2026-08-30 \
		--lane vectorbt

validate:
	$(UV) run fmtrader registry count

noise-calibration:
	$(UV) run fmtrader validate noise-calibration --trials 200 --bars 1500

worker:
	$(UV) run fmtrader worker start

campaign:
	$(UV) run fmtrader campaign new --config configs/campaigns/trial_short.yaml --local

pause:
	@test -n "$(ID)" || (echo "Usage: make pause ID=<campaign_id>"; exit 1)
	$(UV) run fmtrader campaign pause $(ID)

resume:
	@test -n "$(ID)" || (echo "Usage: make resume ID=<campaign_id>"; exit 1)
	$(UV) run fmtrader campaign resume $(ID)

ui:
	$(error Phase 11 not implemented yet — see FRONTEND_SPEC.md)
