'''
tests/unit/test_execution_domain_purity.py

Purity Rule: src/execution/domain may import only the standard library,
its own modules, and src.core (which is itself pure).
'''

import ast
import sys
from pathlib import Path

import pytest

DOMAIN = Path("src/execution/domain")
ALLOWED_INTERNAL = ("src.execution.domain", "src.core")


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()

    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)

    return found


def is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    if top in sys.stdlib_module_names or top == "__future__":
        return True
    return any(module == allowed or module.startswith(allowed + ".") for allowed in ALLOWED_INTERNAL)


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda p: p.name)
def test_domain_module_imports_only_pure_modules(path: Path):
    bad = {module for module in imports_of(path) if not is_allowed(module)}

    assert not bad, f"{path} imports non-pure modules: {bad}"
