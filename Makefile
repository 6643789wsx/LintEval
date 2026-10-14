# LintEval — common entry points.  `make help` lists everything.
PY        ?= python3
MODEL     ?= gpt-6-luna
BASE_URL  ?= $(pku_maas_base_url)
DATA      ?= lite/linteval_lite.jsonl
LIMIT     ?= 0
WORKERS   ?= 4

.PHONY: help setup check sanity smoke demo eval-lite eval-full merge-full tables verify clean

help:  ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## create .venv, install requirements and check system tools
	bash scripts/setup.sh

check:  ## verify packages, system tools and repository layout
	$(PY) scripts/test_environment.py

sanity:  ## end-to-end pipeline check without any API call (~1 min)
	$(PY) scripts/sanity_check.py

smoke:  ## one-sample end-to-end smoke test against $(MODEL)
	$(PY) scripts/smoke_test.py --model $(MODEL)

demo:  ## evaluate N samples of the 100-sample demo (LIMIT=10)
	$(PY) scripts/10_eval_models.py --custom_api --model $(MODEL) \
		--data_path lite/demo_100.jsonl --limit $(LIMIT) --n_workers $(WORKERS)

eval-lite:  ## evaluate the 498-sample lite split
	$(PY) scripts/10_eval_models.py --custom_api --model $(MODEL) \
		--data_path $(DATA) --n_workers $(WORKERS)

eval-full:  ## evaluate the 13,061-sample full split (needs merge-full first)
	$(PY) scripts/10_eval_models.py --custom_api --model $(MODEL) \
		--data_path full/linteval_full.jsonl --n_workers $(WORKERS)

merge-full:  ## rebuild full/linteval_full.jsonl and the Parquet files
	$(PY) scripts/split_dataset.py --merge
	$(PY) scripts/build_dataset_files.py

tables:  ## regenerate the paper LaTeX tables from eval_results/
	$(PY) scripts/11_gen_paper_excel.py

verify:  ## check that per-sample results reproduce the paper metrics and tables
	$(PY) scripts/verify_paper_metrics.py --check-tables

clean:  ## remove local smoke artifacts (never touches released data)
	rm -f eval_results/_smoke_input.jsonl eval_results/smoke_*.json
