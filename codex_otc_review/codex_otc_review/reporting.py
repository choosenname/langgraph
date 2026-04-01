"""Artifact writing utilities for the review scenario."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    """One structured finding captured by the scenario."""

    id: str
    severity: str
    title: str
    evidence: str
    file_refs: list[str]
    why_it_matters: str
    suggested_follow_up: str


def write_artifacts(
    *,
    out_dir: Path,
    report: str,
    findings: list[Finding],
    transcript: list[dict[str, Any]],
) -> None:
    """Write the scenario outputs to disk."""

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report)
    (out_dir / "findings.json").write_text(
        json.dumps([asdict(finding) for finding in findings], indent=2) + "\n"
    )

    transcript_path = out_dir / "transcript.jsonl"
    with transcript_path.open("w", encoding="utf-8") as handle:
        for item in transcript:
            handle.write(json.dumps(item) + "\n")
