import json
from pathlib import Path

from langchain_core.messages import AIMessage

from codex_otc_review.config import ScenarioConfig
from codex_otc_review.runner import ScenarioRunner


class _FakeNode:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def invoke(self, payload: dict[str, object]) -> dict[str, list[AIMessage]]:
        self.calls.append(payload)
        if not self._responses:
            raise AssertionError("no scripted responses remaining")
        return {"messages": [AIMessage(content=self._responses.pop(0))]}


def _config(tmp_path: Path) -> ScenarioConfig:
    return ScenarioConfig(
        project=Path("/home/vlad/Projects/otc-backend"),
        focus="tx-controller",
        max_loops=2,
        model="gpt-5",
        out_dir=tmp_path,
        approval_policy="on-request",
        sandbox_policy="workspace-write",
    )


def test_runner_executes_orchestrator_researcher_reviewer_loop(tmp_path: Path) -> None:
    node = _FakeNode(
        responses=[
            "Initial orchestration scope",
            json.dumps(
                {
                    "summary": "First pass",
                    "findings": [
                        {
                            "id": "F-001",
                            "severity": "medium",
                            "title": "Possible queue race",
                            "evidence": "Queue updates happen in two paths.",
                            "file_refs": [
                                "servers/limitless-tx-controller/src/server/tasks/mod.rs"
                            ],
                            "why_it_matters": "Hidden failure states are possible.",
                            "suggested_follow_up": "Verify transaction boundaries.",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "approved": False,
                    "needs_more_research": True,
                    "blocking_gaps": ["Need stronger evidence for queue ordering"],
                }
            ),
            json.dumps(
                {
                    "summary": "Second pass",
                    "findings": [
                        {
                            "id": "F-002",
                            "severity": "high",
                            "title": "Confirmed queue race",
                            "evidence": "Worker and cleanup path update the same rows.",
                            "file_refs": [
                                "servers/limitless-tx-controller/src/server/tasks/mod.rs",
                                "servers/limitless-tx-controller/src/server/api/mod.rs",
                            ],
                            "why_it_matters": "State can flap under concurrent load.",
                            "suggested_follow_up": "Add locking or isolate transitions.",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "approved": True,
                    "needs_more_research": False,
                    "blocking_gaps": [],
                }
            ),
            "# Final Report\n\nApproved with one high-severity finding.\n",
        ]
    )

    result = ScenarioRunner(config=_config(tmp_path), node=node).run()

    assert result.findings[0].id == "F-002"
    assert result.findings[0].severity == "high"
    assert [entry["role"] for entry in result.transcript] == [
        "orchestrator",
        "researcher",
        "reviewer",
        "researcher",
        "reviewer",
        "orchestrator",
    ]
    assert (tmp_path / "report.md").exists()
    assert len(node.calls) == 6


def test_runner_stops_after_approval(tmp_path: Path) -> None:
    node = _FakeNode(
        responses=[
            "Initial orchestration scope",
            json.dumps(
                {
                    "summary": "Only pass",
                    "findings": [
                        {
                            "id": "F-003",
                            "severity": "low",
                            "title": "Missing metrics label",
                            "evidence": "Metric omits status tag.",
                            "file_refs": [
                                "servers/limitless-tx-controller/src/server/metrics/mod.rs"
                            ],
                            "why_it_matters": "Alert triage is weaker.",
                            "suggested_follow_up": "Add status label coverage.",
                        }
                    ],
                }
            ),
            json.dumps(
                {
                    "approved": True,
                    "needs_more_research": False,
                    "blocking_gaps": [],
                }
            ),
            "# Final Report\n\nApproved after one loop.\n",
        ]
    )

    result = ScenarioRunner(config=_config(tmp_path), node=node).run()

    assert result.findings[0].id == "F-003"
    assert len(result.transcript) == 4
    assert len(node.calls) == 4


def test_runner_writes_expected_artifact_names(tmp_path: Path) -> None:
    node = _FakeNode(
        responses=[
            "Initial orchestration scope",
            json.dumps({"summary": "Only pass", "findings": []}),
            json.dumps(
                {
                    "approved": True,
                    "needs_more_research": False,
                    "blocking_gaps": [],
                }
            ),
            "# Final Report\n\nNo findings.\n",
        ]
    )

    ScenarioRunner(config=_config(tmp_path), node=node).run()

    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "findings.json").exists()
    assert (tmp_path / "transcript.jsonl").exists()
