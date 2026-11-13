.PHONY: install test typecheck check firewall certs clean

install:
	pip install -r requirements.txt

test:
	pytest -v

typecheck:
	mypy --strict src/ tests/

check: typecheck test

firewall:
	chmod +x config/setup_firewall.sh && ./config/setup_firewall.sh

certs:
	chmod +x config/generate_certs.sh && ./config/generate_certs.sh

clean:
	rm -rf .pytest_cache .mypy_cache __pycache__ src/__pycache__ tests/__pycache__
