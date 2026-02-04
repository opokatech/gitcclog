all:
	@echo "release     - generate a changelog, commit and tag it"
	@echo "dry-release - only generate a changelog"
	@echo "tests       - run tests"

release:
	python3 gitcclog.py --config gitcclog_github.json --real-run

dry-release:
	python3 gitcclog.py --config gitcclog_github.json

tests:
	python3 gitcclog_test.py
