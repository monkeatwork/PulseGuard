.PHONY: up down data test

up:
	docker compose up --build

down:
	docker compose down -v

# Fetches the Wiefling RBA dataset from Zenodo (record 10.5281/zenodo.6782156).
# Idempotent: re-running skips files whose checksum already matches data/manifests/.
# No synthetic fallback — a fetch failure halts with an explicit error (see DECISIONS.md).
data:
	python -m benchmark.generator.rba_loader --record-id $${RBA_ZENODO_RECORD_ID:-6782156} --out data/raw

test:
	pytest -q
