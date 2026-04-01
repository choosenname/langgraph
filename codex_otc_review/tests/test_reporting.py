import json
from pathlib import Path

from codex_otc_review.reporting import Finding, write_artifacts


def test_write_report_artifacts(tmp_path: Path) -> None:
    findings = [
        Finding(
            id="F-001",
            severity="high",
            title="Missing queue isolation",
            evidence="Worker and API paths update the same row set.",
            file_refs=["servers/limitless-tx-controller/src/server/tasks/mod.rs"],
            why_it_matters="Concurrent updates can hide failures.",
            suggested_follow_up="Audit transaction boundaries.",
        )
    ]
    transcript = [
        {
            "role": "researcher",
            "loop_index": 1,
            "prompt": "Inspect tx-controller queue flow",
            "response": "Found a potential race around queue updates.",
        }
    ]

    write_artifacts(
        out_dir=tmp_path,
        report="# Summary\n\nOne issue found.\n",
        findings=findings,
        transcript=transcript,
    )

    assert (tmp_path / "report.md").read_text() == "# Summary\n\nOne issue found.\n"
    findings_payload = json.loads((tmp_path / "findings.json").read_text())
    assert findings_payload[0]["id"] == "F-001"
    transcript_lines = (tmp_path / "transcript.jsonl").read_text().strip().splitlines()
    assert len(transcript_lines) == 1
    assert json.loads(transcript_lines[0])["role"] == "researcher"
