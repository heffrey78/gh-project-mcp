#!/usr/bin/env python3
"""Print each tool's definition size and the total against the budget in tests/tool_surface_budget.json."""

import json
from pathlib import Path

from gh_project_mcp.surface import definition_sizes

sizes = definition_sizes()
budget = json.loads((Path(__file__).parent.parent / "tests" / "tool_surface_budget.json").read_text())
for name, size in sorted(sizes.items(), key=lambda item: -item[1]):
    print(f"{size:6d}  {name}")
total = f"{sum(sizes.values()):6d}  total of {len(sizes)} tools"
print(f"{total} (budget {budget['max_chars']} chars, {budget['max_tools']} tools)")
