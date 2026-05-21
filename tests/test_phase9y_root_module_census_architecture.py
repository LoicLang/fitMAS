from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "backend" / "src" / "fitmas"
CENSUS = ROOT / "docs" / "ROOT-MODULE-CENSUS.md"

ALLOWED_ACTIONS = {
    "delete",
    "merge",
    "move",
    "keep_root_temporarily",
    "entrypoint",
}
ALLOWED_OWNERS = {
    "app/api",
    "app/telegram",
    "core",
    "decision",
    "domain/planning",
    "domain/execution",
    "domain/memory",
    "domain/athlete",
    "domain/coaching",
    "integrations",
    "llm",
    "tools",
    "legacy/delete",
    "root-entrypoint",
}


def _root_modules() -> set[str]:
    return {path.name for path in SRC_ROOT.glob("*.py")}


def _census_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        filename = cells[0].strip("`")
        rows[filename] = {
            "owner": cells[1],
            "action": cells[2],
            "reason": cells[3],
            "next": cells[4],
        }
    return rows


def test_9y_root_module_census_exists_with_front_matter() -> None:
    assert CENSUS.exists()
    source = CENSUS.read_text(encoding="utf-8")
    assert source.startswith("---\n")
    assert "summary:" in source
    assert "read_when:" in source
    assert "## Classification" in source


def test_9y_every_root_module_has_exactly_one_census_row() -> None:
    rows = _census_rows()
    assert set(rows) == _root_modules()


def test_9y_every_census_row_has_owner_action_and_next_slice() -> None:
    rows = _census_rows()
    offenders: list[str] = []
    for filename, row in rows.items():
        if row["owner"] not in ALLOWED_OWNERS:
            offenders.append(f"{filename}: owner={row['owner']}")
        if row["action"] not in ALLOWED_ACTIONS:
            offenders.append(f"{filename}: action={row['action']}")
        if not row["reason"] or row["reason"] == "-":
            offenders.append(f"{filename}: missing reason")
        if not row["next"] or row["next"] == "-":
            offenders.append(f"{filename}: missing next slice")
    assert offenders == []


def test_9y_census_is_delete_first_not_move_only() -> None:
    rows = _census_rows()
    actions = [row["action"] for row in rows.values()]

    assert actions.count("delete") == 0
    assert actions.count("merge") >= 10
    assert actions.count("move") < len(actions)


def test_9y_root_entrypoints_are_explicitly_bounded() -> None:
    rows = _census_rows()
    entrypoints = {filename for filename, row in rows.items() if row["action"] == "entrypoint"}

    assert entrypoints == {"__init__.py", "api.py", "main.py"}
