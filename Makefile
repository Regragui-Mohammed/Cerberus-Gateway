PYTHON ?= $(shell if [ -f venv/bin/python ]; then echo venv/bin/python; else echo python3; fi)
PYTEST ?= $(shell if [ -f venv/bin/pytest ]; then echo venv/bin/pytest; else echo pytest; fi)
MYPY ?= $(shell if [ -f venv/bin/mypy ]; then echo venv/bin/mypy; else echo mypy; fi)

.PHONY: install test typecheck check firewall certs up down run demo attack clean

install:
	pip install -r requirements.txt

test:
	$(PYTEST) -v

typecheck:
	$(MYPY) --strict src/ tests/

check: typecheck test

firewall:
	chmod +x config/setup_firewall.sh && ./config/setup_firewall.sh

certs:
	chmod +x config/generate_certs.sh && ./config/generate_certs.sh

up:
	docker compose up -d

down:
	docker compose down

run:
	$(PYTHON) -m src.main

demo:
	$(PYTHON) scripts/simulate_demo.py

attack:
	$(PYTHON) scripts/simulate_demo.py --attack

clean:
	rm -rf .pytest_cache .mypy_cache __pycache__ src/__pycache__ tests/__pycache__
