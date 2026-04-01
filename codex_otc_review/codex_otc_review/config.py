"""Configuration helpers for the Codex OTC review scenario."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScenarioConfig:
    """Resolved runtime configuration for one scenario run."""

    project: Path
    focus: str
    max_loops: int
    model: str
    out_dir: Path
    approval_policy: str
    sandbox_policy: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the scenario runner."""

    parser = argparse.ArgumentParser(prog="codex-otc-review")
    parser.add_argument("--project", required=True)
    parser.add_argument("--focus", default="architecture")
    parser.add_argument("--max-loops", type=int, default=2)
    parser.add_argument("--model", default="gpt-5")
    parser.add_argument("--out-dir", default="artifacts/codex-otc-review")
    parser.add_argument("--approval-policy", default="on-request")
    parser.add_argument("--sandbox-policy", default="workspace-write")
    return parser.parse_args(argv)


def parse_config(args: argparse.Namespace) -> ScenarioConfig:
    """Convert parsed CLI arguments into normalized runtime config."""

    return ScenarioConfig(
        project=Path(args.project),
        focus=args.focus,
        max_loops=args.max_loops,
        model=args.model,
        out_dir=Path(args.out_dir),
        approval_policy=args.approval_policy,
        sandbox_policy=args.sandbox_policy,
    )
