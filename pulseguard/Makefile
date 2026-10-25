# Day-to-day use: the scripts at the repository root (config-everything,
# run, stop). These targets are the OFFLINE research pipeline -- run them
# only to regenerate the benchmark, retrain the models and re-evaluate.
# They need the dev environment: pip install -r requirements-dev.txt

PY ?= python
SEED ?= 42
SCALE ?= 50000
EVENTS := data/generated/events.parquet
MODELS := services/detection_engine/app/model_registry

.PHONY: data generate baselines train evaluate report demo pipeline test research

# Fetches the Wiefling RBA dataset from Zenodo (record 10.5281/zenodo.6782156).
# Idempotent; no synthetic fallback -- a failed fetch halts (DECISIONS.md).
data:
	$(PY) -m benchmark.generator.rba_loader --record-id $${RBA_ZENODO_RECORD_ID:-6782156} --out data/raw

generate: data
	$(PY) -m benchmark.generator.cli --seed $(SEED) --scale $(SCALE) --rba-zip data/raw/rba-dataset.zip --out data/generated
	$(PY) -m benchmark.generator.episode_lengths --events $(EVENTS) --out eval/results/episode_lengths.json

baselines:
	$(PY) -m eval.harness.run_eval --events $(EVENTS) --seed $(SEED)

train:
	$(PY) -m services.detection_engine.app.train_stage_b --events $(EVENTS) --seed $(SEED)
	$(PY) -m services.detection_engine.app.train_stage_c --events $(EVENTS) --seed $(SEED)
	$(PY) -m services.detection_engine.app.tune_fusion_weights --events $(EVENTS) --seed $(SEED)

evaluate:
	$(PY) -m eval.ablation.run_ablation --events $(EVENTS) --seed $(SEED)
	$(PY) -m eval.adversarial.run_adversarial_eval --events $(EVENTS) --seed $(SEED)

# The frozen harness report, then the research sections (eval/research/report.py),
# each generated from eval/results/*.json only.
report:
	$(PY) -c "from pathlib import Path; from eval.harness.report import build_final_report; from eval.research.report import build_research_sections; r = Path('eval/results'); r.joinpath('final_report.md').write_text(build_final_report(r) + '\n' + build_research_sections(r) + '\n')"

# Small labelled slice of the TEST split shipped with the repo, so the live
# demo never needs the 1.1 GB dataset.
demo:
	$(PY) -m benchmark.generator.demo_slice --events $(EVENTS) --seed $(SEED) --out data/demo/demo_events.parquet

# Research experiments (HANDOFF.md tasks 1-4; DECISIONS.md 2026-10-26). They train
# in memory and never touch model_registry/. Hours at full scale: lower SCALE to try.
SEEDS ?= 42 1 2 3 4
research: data
	$(PY) -m eval.research.fatigue_sweep --scale $(SCALE) --seeds $(SEEDS) --out eval/results/fatigue_sweep.json --plot eval/results/fatigue_sweep.png
	$(PY) -m eval.research.fatigue_sweep --scale $(SCALE) --seeds $(SEED) --fatigue-null legacy --no-grid --out eval/results/fatigue_sweep_legacy.json --plot eval/results/fatigue_sweep_legacy.png
	$(PY) -m eval.research.before_capitulation --scale $(SCALE) --seed $(SEED) --strengths 1.0 --out eval/results/before_capitulation.json
	$(PY) -m eval.research.adaptive_attacker --scale $(SCALE) --seed $(SEED) --out eval/results/adaptive_attacker.json --plot eval/results/adaptive_attacker.png
	$(PY) -m eval.research.robustness --scale $(SCALE) --seed $(SEED) --out eval/results/robustness.json

pipeline: generate baselines train evaluate report demo

test:
	$(PY) -m pytest -q --ignore=tests/integration
