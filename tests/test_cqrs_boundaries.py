"""Structural tests for the boundaries the architecture actually rests on.

CQRS léger is a discipline in the code, not a piece of infrastructure — which
means nothing enforces it at runtime and it decays the first time someone in a
hurry imports the convenient thing. These tests read the import graph and fail
when a boundary is crossed, so the rule survives contact with a deadline.

The same applies to the dependency rule (`domain` depends on nothing): it is the
property that makes this module extractable later, and it is invisible until it
is already broken.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "identity_app"
IDENTITY = ROOT / "modules" / "identity"


def _imports(path: Path) -> set[str]:
    """Every module name imported by `path`, dotted and absolute."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _python_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("path", _python_files(IDENTITY / "application" / "queries"), ids=lambda p: p.name)
def test_a_query_never_touches_the_write_side(path: Path):
    imported = _imports(path)

    forbidden = {name for name in imported if "write_repository" in name}
    assert not forbidden, f"{path.name} lit le dépôt d'écriture : {sorted(forbidden)}"

    commands = {name for name in imported if ".application.commands" in name}
    assert not commands, f"{path.name} déclenche une commande : {sorted(commands)}"


@pytest.mark.parametrize("path", _python_files(IDENTITY / "application" / "commands"), ids=lambda p: p.name)
def test_a_command_never_reads_through_the_read_side(path: Path):
    imported = _imports(path)

    reads = {name for name in imported if "read_repository" in name}
    assert not reads, (
        f"{path.name} passe par le dépôt de lecture : {sorted(reads)}. "
        "Une commande lit toujours frais, via le write_repository."
    )

    queries = {name for name in imported if ".application.queries" in name}
    assert not queries, f"{path.name} appelle une query : {sorted(queries)}"


@pytest.mark.parametrize("path", _python_files(IDENTITY / "domain"), ids=lambda p: p.name)
def test_the_domain_depends_on_nothing(path: Path):
    imported = _imports(path)

    technical = {
        name
        for name in imported
        if name.split(".")[0] in {"fastapi", "sqlalchemy", "redis", "jwt", "httpx", "pydantic", "argon2"}
    }
    assert not technical, f"{path.name} dépend d'une techno : {sorted(technical)}"

    outward = {
        name
        for name in imported
        if name.startswith("identity_app")
        and ".domain" not in name
    }
    assert not outward, f"{path.name} dépend d'une couche extérieure : {sorted(outward)}"


@pytest.mark.parametrize("path", _python_files(IDENTITY / "presentation"), ids=lambda p: p.name)
def test_presentation_does_not_reach_past_the_application_layer(path: Path):
    """Routers talk to commands and queries. A router building its own
    repository would put a second copy of the wiring outside `core.deps`, and
    the two would drift."""
    imported = _imports(path)

    repositories = {
        name for name in imported if "write_repository" in name or "read_repository" in name
    }
    # `MAX_PAGE_SIZE` is a validation bound, not data access — the admin router
    # imports it to declare its query parameter, which is legitimate.
    repositories -= {
        "identity_app.modules.identity.infra.read_repository.MAX_PAGE_SIZE",
        "identity_app.modules.identity.infra.read_repository",
    }
    assert not repositories, f"{path.name} accède directement à un dépôt : {sorted(repositories)}"


def test_the_consumer_contract_stays_dependency_light():
    """`identity_provider.py` is meant to be copied into Wallet, Fund, Ride and
    the rest. The moment it imports something from `identity_app`, it stops
    being copyable and every consumer inherits this service's internals."""
    path = ROOT / "shared_kernel" / "contracts" / "identity_provider.py"

    internal = {name for name in _imports(path) if name.startswith("identity_app")}

    assert not internal, f"Le port consommateur dépend du service : {sorted(internal)}"
