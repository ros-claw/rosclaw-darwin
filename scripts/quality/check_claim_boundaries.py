#!/usr/bin/env python3
"""Claim boundary linter for ROSClaw-Darwin v1.0.

Scans docs and reports for unsupported phrases and validates evidence cards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

DEFAULT_UNSUPPORTED_PHRASES = [
    "validated transferable skill",
    "large-yaw solved",
    "official Arena leaderboard",
    "procedural OOD success",
]


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


ALLOWED_CONTEXT_KEYWORDS = (
    "blocked",
    "cannot",
    "can't",
    "do not",
    "don't",
    "not claim",
    "disallowed",
    "without",
    "should not",
    "must not",
    "is not",
    "are not",
    "no ",
    "not a ",
    "not an ",
    "unless",
    "required",
    "not claimed",
)


def _is_allowed_context(line: str) -> bool:
    """Allow unsupported phrases when they appear in a negated/disclaimer context."""
    lower = line.lower()
    return any(keyword in lower for keyword in ALLOWED_CONTEXT_KEYWORDS)


def scan_text(text: str, phrases: list[str]) -> list[tuple[str, int, str]]:
    """Return list of (phrase, line_number, line_text) violations."""
    violations = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        if _is_allowed_context(line):
            continue
        for phrase in phrases:
            if phrase.lower() in lower:
                violations.append((phrase, line_no, line.strip()))
    return violations


def scan_directory(directory: Path, phrases: list[str], suffixes: tuple[str, ...] = (".md", ".yaml", ".yml"), exclude_patterns: tuple[str, ...] = ()) -> dict[Path, list[tuple[str, int, str]]]:
    results: dict[Path, list[tuple[str, int, str]]] = {}
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in suffixes:
            if any(pattern in path.name for pattern in exclude_patterns):
                continue
            violations = scan_text(path.read_text(encoding="utf-8"), phrases)
            if violations:
                results[path] = violations
    return results


def check_evidence_cards(cards_dir: Path, required_cards: list[str]) -> list[str]:
    errors = []
    if not cards_dir.exists():
        errors.append(f"Cards directory not found: {cards_dir}")
        return errors
    found = {p.stem.replace(".card", "") for p in cards_dir.glob("*.card.yaml")}
    for name in required_cards:
        if name not in found:
            errors.append(f"Missing required evidence card: {name}")
    return errors


def collect_v1_paths(root: Path, include_globs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in include_globs:
        paths.extend(root.glob(pattern))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint Darwin v1.0 claim boundaries")
    parser.add_argument("--config", type=Path, default=Path("configs/release/darwin_v1_release_gate.yaml"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--cards-dir", type=Path, default=Path("cards"))
    parser.add_argument("--demo-pack-dir", type=Path, default=Path("demo_pack"))
    parser.add_argument("--release-dir", type=Path, default=Path("release/darwin_v1"))
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    phrases = config.get("unsupported_phrases", DEFAULT_UNSUPPORTED_PHRASES)
    required_cards = config.get("required_cards", [])

    violations: dict[Path, list[tuple[str, int, str]]] = {}
    for path in collect_v1_paths(args.docs_dir, ["DARWIN_*.md"]):
        v = scan_text(path.read_text(encoding="utf-8"), phrases)
        if v:
            violations[path] = v
    for path in collect_v1_paths(args.reports_dir, ["INDEX_V1.md", "FINAL_DARWIN_V1_RELEASE_REPORT.md"]):
        v = scan_text(path.read_text(encoding="utf-8"), phrases)
        if v:
            violations[path] = v
    for directory in [args.demo_pack_dir, args.release_dir]:
        if directory.exists():
            for path in directory.rglob("*.md"):
                v = scan_text(path.read_text(encoding="utf-8"), phrases)
                if v:
                    violations[path] = v

    card_errors = check_evidence_cards(args.cards_dir, required_cards)

    exit_code = 0
    if violations:
        print("\nUnsupported claims in v1.0 documents:")
        for path, items in sorted(violations.items()):
            for phrase, line_no, line in items:
                print(f"  {path}:{line_no}: {phrase!r} -> {line}")
        exit_code = 1

    if card_errors:
        print("\nEvidence card errors:")
        for err in card_errors:
            print(f"  {err}")
        exit_code = 1

    if exit_code == 0:
        print("Claim boundary check passed.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
