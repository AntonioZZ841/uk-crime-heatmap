PY := .venv/bin/python

.PHONY: all mini download db verify serve clean-db

all: download db verify        ## full pipeline: 12 months, all forces

mini:                          ## 1 month, 3 forces - proves the chain end to end
	MINI_MODE=1 $(PY) -m pipeline.run_all

download:                      ## crime CSVs + boundaries + lookup + population
	$(PY) -m pipeline.download

db:                            ## load everything into data/crime.duckdb + aggregates
	$(PY) -m pipeline.run_all --skip-download

verify:                        ## checkpoint report (row counts, join coverage, rate sanity)
	$(PY) -m pipeline.verify

PORT ?= 8000
serve:                         ## run the app on http://localhost:$(PORT)  (make serve PORT=8017)
	$(PY) -m uvicorn backend.app:app --host 0.0.0.0 --port $(PORT)

clean-db:
	rm -f data/crime.duckdb
