#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
# superpowers/ is the skills working area (specs/plans), never project docs:
# excluded in BOTH modes. archive/ + research/ are historical: shown with --all.
ALWAYS_EXCLUDED_DIRS = {"superpowers"}
HISTORICAL_DIRS = {"archive", "research"}
DEFAULT_EXCLUDED_DIRS = ALWAYS_EXCLUDED_DIRS | HISTORICAL_DIRS


def walk_markdown_files(root: Path, *, include_all: bool = False) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if any(part in ALWAYS_EXCLUDED_DIRS for part in rel.parts):
            continue
        if not include_all and any(part in HISTORICAL_DIRS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: str(item.relative_to(root)))


def extract_metadata(full_path: Path) -> tuple[str | None, list[str], str | None]:
    content = full_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None, [], "missing front matter"

    end_index = content.find("\n---", 3)
    if end_index == -1:
        return None, [], "unterminated front matter"

    front_matter = content[3:end_index].strip()
    lines = front_matter.splitlines()

    summary_raw: str | None = None
    read_when: list[str] = []
    in_read_when = False

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("summary:"):
            summary_raw = line.split("summary:", 1)[1].strip()
            in_read_when = False
            continue
        if line.startswith("read_when:"):
            inline = line.split("read_when:", 1)[1].strip()
            in_read_when = True
            if inline.startswith("[") and inline.endswith("]"):
                values = inline[1:-1]
                for item in values.split(","):
                    normalized = item.strip().strip("'\"")
                    if normalized:
                        read_when.append(normalized)
            continue
        if in_read_when:
            if line.startswith("- "):
                hint = line[2:].strip()
                if hint:
                    read_when.append(hint)
                continue
            if line == "":
                continue
            in_read_when = False

    if summary_raw is None:
        return None, read_when, "summary key missing"

    summary = summary_raw.strip().strip("'\"")
    summary = " ".join(summary.split())
    if not summary:
        return None, read_when, "summary is empty"

    return summary, read_when, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List FitMAS docs with front-matter summaries.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="include archive and superpowers historical plan docs",
    )
    args = parser.parse_args(argv)

    if not DOCS_DIR.exists():
        print("docs directory not found.")
        return 1

    if args.all:
        print("Listing all markdown files in docs folder, including archive and historical plans:")
    else:
        print("Listing active markdown docs. Use ./scripts/docs:list --all for archive and historical plans:")
    markdown_files = walk_markdown_files(DOCS_DIR, include_all=args.all)

    for full_path in markdown_files:
        rel = full_path.relative_to(DOCS_DIR)
        summary, read_when, error = extract_metadata(full_path)
        if summary is None:
            suffix = f" - [{error}]" if error else ""
            print(f"{rel}{suffix}")
            continue
        print(f"{rel} - {summary}")
        if read_when:
            print(f"  Read when: {'; '.join(read_when)}")

    print(
        "\nReminder: keep docs up to date as behavior changes. "
        'When your task matches any "Read when" hint above, read that doc before coding.'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
