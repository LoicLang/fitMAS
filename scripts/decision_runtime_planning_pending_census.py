#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, NamedTuple


TARGETS: tuple[tuple[str, str], ...] = (
    ("legacy/conversation_canonical_planning_bridge.py", "planning"),
    ("legacy/conversation_pending_bridge.py", "pending"),
    ("legacy/conversation_planning_bridge.py", "planning_reply"),
    ("legacy/planning_runtime_adapter.py", "planning"),
    ("legacy/planning_outcome_adapter.py", "planning_reply"),
    ("legacy/plan_patch_reply_adapter.py", "planning_reply"),
    ("legacy/pending_reply_adapter.py", "pending_reply"),
)


class Target(NamedTuple):
    path: str
    owner: str
    module: str
    short_name: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Census FitMAS planning/pending legacy runtime surfaces.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)

    census = build_census(args.root)
    print_summary(census)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(census, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0


def build_census(root: Path) -> dict[str, Any]:
    root = root.resolve()
    src = root / "backend" / "src" / "fitmas"
    targets = tuple(_target(path, owner) for path, owner in TARGETS)
    entries = [_module_entry(src, target, targets) for target in targets]
    status_counts: dict[str, int] = {}
    owner_counts: dict[str, int] = {}
    for entry in entries:
        status_counts[entry["status"]] = status_counts.get(entry["status"], 0) + 1
        owner_counts[entry["owner"]] = owner_counts.get(entry["owner"], 0) + 1
    return {
        "module_count": len(entries),
        "runtime_active_count": status_counts.get("runtime_active", 0),
        "legacy_internal_count": status_counts.get("legacy_internal", 0),
        "test_only_count": status_counts.get("test_only", 0),
        "deleted_count": status_counts.get("deleted", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "owner_counts": dict(sorted(owner_counts.items())),
        "modules": entries,
    }


def print_summary(census: dict[str, Any]) -> None:
    print(f"module_count={census['module_count']}")
    print(f"runtime_active_count={census['runtime_active_count']}")
    print(f"legacy_internal_count={census['legacy_internal_count']}")
    print(f"test_only_count={census['test_only_count']}")
    print(f"deleted_count={census['deleted_count']}")
    for entry in census["modules"]:
        print(
            f"{entry['path']} owner={entry['owner']} status={entry['status']} "
            f"lines={entry['line_count']} runtime_importers={len(entry['runtime_importers'])} "
            f"runtime_symbols={','.join(entry['runtime_symbols']) or '-'}"
        )
        for importer in entry["runtime_importers"]:
            print(f"  runtime_importer {importer}")


def _target(path: str, owner: str) -> Target:
    module = f"fitmas.{path[:-3].replace('/', '.')}"
    return Target(
        path=path,
        owner=owner,
        module=module,
        short_name=Path(path).stem,
    )


def _module_entry(src: Path, target: Target, targets: tuple[Target, ...]) -> dict[str, Any]:
    target_path = src / target.path
    exists = target_path.exists()
    source = target_path.read_text(encoding="utf-8") if exists else ""
    runtime_importers: set[str] = set()
    test_importers: set[str] = set()
    runtime_symbols: set[str] = set()

    for path in sorted(src.rglob("*.py")):
        if path == target_path:
            continue
        rel = path.relative_to(src).as_posix()
        usage = _target_usage(path, target)
        if usage.imported:
            runtime_importers.add(rel)
            runtime_symbols.update(usage.symbols)

    tests_root = src.parents[2] / "tests"
    if tests_root.exists():
        for path in sorted(tests_root.rglob("*.py")):
            usage = _target_usage(path, target)
            if usage.imported:
                test_importers.add(path.relative_to(tests_root).as_posix())

    return {
        "path": target.path,
        "module": target.module,
        "owner": target.owner,
        "status": _status(runtime_importers, exists=exists),
        "line_count": len(source.splitlines()),
        "public_defs": _public_defs(source),
        "runtime_importers": sorted(runtime_importers),
        "test_importers": sorted(test_importers),
        "runtime_symbols": sorted(runtime_symbols),
        "next_action": _next_action(target, runtime_importers),
    }


class Usage(NamedTuple):
    imported: bool
    symbols: frozenset[str]


def _target_usage(path: Path, target: Target) -> Usage:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return Usage(imported=False, symbols=frozenset())

    module_aliases: set[str] = set()
    direct_symbols: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == target.module:
                    module_aliases.add(alias.asname or target.short_name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "fitmas.legacy":
                for alias in node.names:
                    if alias.name == target.short_name:
                        module_aliases.add(alias.asname or alias.name)
            elif node.module == target.module:
                for alias in node.names:
                    direct_symbols.add(alias.asname or alias.name)

    imported = bool(module_aliases or direct_symbols)
    symbols = set(direct_symbols)
    if module_aliases:
        symbols.update(_attribute_symbols(tree, module_aliases))
    return Usage(imported=imported, symbols=frozenset(symbols))


def _attribute_symbols(tree: ast.AST, module_aliases: set[str]) -> set[str]:
    symbols: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id in module_aliases:
            symbols.add(node.attr)
    return symbols


def _public_defs(source: str) -> list[str]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            names.append(node.name)
    return names


def _status(runtime_importers: set[str], *, exists: bool) -> str:
    if not exists:
        return "deleted_referenced" if runtime_importers else "deleted"
    if any(not item.startswith("legacy/") for item in runtime_importers):
        return "runtime_active"
    if runtime_importers:
        return "legacy_internal"
    return "test_only"


def _next_action(target: Target, runtime_importers: set[str]) -> str:
    if target.path == "legacy/conversation_canonical_planning_bridge.py":
        return "extract typed planning preparation/handling into decision + domain/planning, then delete bridge"
    if target.path == "legacy/conversation_pending_bridge.py":
        return "extract pending resolution service into decision, then delete bridge"
    if target.path in {"legacy/pending_reply_adapter.py", "legacy/plan_patch_reply_adapter.py"}:
        return "move outcome composition into decision reply layer once parent bridge is gone"
    if not runtime_importers:
        return "delete after test imports move to canonical owner"
    return "collapse into parent canonical service or delete after parent bridge extraction"


if __name__ == "__main__":
    raise SystemExit(main())
