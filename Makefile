# Test tiers (see docs/STRATEGY_2026Q4.md, "Engineering rules").
#   make test-quick  every commit: format, lint, unit tests; skips real-CAD tests (~1-3 min)
#   make test-full   before a merge: quick tier + real-CAD tests + deterministic smoke run
#
# Real-CAD tests are Rust tests marked #[ignore = "real CAD ..."] and pytest tests
# marked @pytest.mark.cad. They build and audit actual hulls with OpenCascade.

PY ?= $(CURDIR)/.venv/bin/python
CARGO ?= cargo
export MARINAFRAME_TEST_PYTHON ?= $(PY)
export PATH := $(dir $(PY)):$(PATH)

CAD_RUST_TESTS = --test finalization_guards --test validation_matrix --test audit_identity --test draft_guards --test region_pipeline --test investigation_guards

.PHONY: test-quick test-full lint rust-quick python-quick rust-cad python-cad smoke secrets

test-quick: lint rust-quick python-quick secrets

test-full: test-quick rust-cad python-cad smoke

lint:
	$(CARGO) fmt --all --check
	$(CARGO) clippy --locked --workspace --all-targets -- -D warnings

rust-quick:
	$(CARGO) test --locked --workspace

python-quick:
	$(PY) -m pytest -q -p no:cacheprovider -m "not cad"

rust-cad:
	$(CARGO) test --locked -p marinaframe-control $(CAD_RUST_TESTS) -- --ignored --test-threads=1
	$(CARGO) test --locked -p marinaframe-app-core --test real_task -- --ignored

python-cad:
	$(PY) -m pytest -q -p no:cacheprovider -m cad

# Deterministic end-to-end run: must end awaiting_human_review and verify as valid.
smoke:
	$(CARGO) build --release --locked -p marinaframe-control
	@set -e; run=$$(mktemp -d /tmp/marinaframe-run.XXXXXX); \
	$(PY) examples/make_agent_example.py --out $$run/input >/dev/null; \
	target/release/marinaframe run --task $$run/task --source $$run/input/spec.json \
	  --worker-python $(PY) --policy deterministic | grep -q '"status":"awaiting_human_review"'; \
	target/release/marinaframe verify --task $$run/task | grep -q '"valid":true'; \
	echo "smoke: awaiting_human_review, valid ($$run)"

secrets:
	$(PY) scripts/scan_secrets.py
