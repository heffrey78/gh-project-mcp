.PHONY: lint test smoke surface

# What CI runs, exactly. Run before pushing.
lint:
	uv run --extra dev ruff check src tests scripts
	uv run --extra dev ruff format --check src tests scripts

test:
	uv run --extra test pytest

# Start the server over stdio and check the handshake and stdout purity.
smoke:
	uv run python scripts/mcp_handshake_smoke.py

# Tool definition sizes, per tool.
surface:
	uv run python scripts/tool_surface_report.py
