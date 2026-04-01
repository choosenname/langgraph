"""Scenario runner for the Codex OTC review package."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from codex_otc_review.config import ScenarioConfig
from codex_otc_review.prompts import (
    build_orchestrator_prompt,
    build_researcher_prompt,
    build_reviewer_prompt,
)
from codex_otc_review.reporting import Finding, write_artifacts


@dataclass(frozen=True)
class ScenarioResult:
    """Structured outputs from one completed review scenario run."""

    report: str
    findings: list[Finding]
    transcript: list[dict[str, Any]]


class ScenarioRunner:
    """Drive the orchestrator, researcher, and reviewer loop."""

    def __init__(self, *, config: ScenarioConfig, node: Any) -> None:
        self.config = config
        self.node = node
        self._messages: list[BaseMessage] = [
            SystemMessage(
                content=(
                    "You are participating in a read-only repository review scenario. "
                    "Do not edit files, apply patches, or propose destructive commands."
                )
            )
        ]

    def run(self) -> ScenarioResult:
        transcript: list[dict[str, Any]] = []

        kickoff = self._turn(
            role="orchestrator",
            loop_index=0,
            prompt=build_orchestrator_prompt(
                str(self.config.project), self.config.focus, self.config.max_loops
            ),
            transcript=transcript,
        )

        findings: list[Finding] = []
        reviewer_feedback: str | None = None

        for loop_index in range(1, self.config.max_loops + 1):
            researcher_output = self._turn(
                role="researcher",
                loop_index=loop_index,
                prompt=build_researcher_prompt(
                    str(self.config.project), self.config.focus, reviewer_feedback
                ),
                transcript=transcript,
            )
            findings = self._parse_findings(researcher_output)

            reviewer_output = self._turn(
                role="reviewer",
                loop_index=loop_index,
                prompt=build_reviewer_prompt(
                    str(self.config.project), self.config.focus, researcher_output
                ),
                transcript=transcript,
            )
            review = self._parse_review_decision(reviewer_output)
            if review["approved"]:
                break
            reviewer_feedback = "; ".join(review["blocking_gaps"]) or reviewer_output
        else:  # pragma: no cover - defensive fallback
            reviewer_feedback = reviewer_feedback or "Max loops reached without approval."

        final_prompt = (
            "Produce the final markdown report for this scenario.\n"
            f"Initial orchestration scope:\n{kickoff}\n\n"
            f"Final findings JSON:\n{json.dumps([finding.__dict__ for finding in findings], indent=2)}\n"
        )
        report = self._turn(
            role="orchestrator",
            loop_index=len([entry for entry in transcript if entry["role"] == "reviewer"]),
            prompt=final_prompt,
            transcript=transcript,
        )

        write_artifacts(
            out_dir=self.config.out_dir,
            report=report,
            findings=findings,
            transcript=transcript,
        )
        return ScenarioResult(report=report, findings=findings, transcript=transcript)

    def _turn(
        self,
        *,
        role: str,
        loop_index: int,
        prompt: str,
        transcript: list[dict[str, Any]],
    ) -> str:
        role_prompt = f"ROLE: {role}\n\n{prompt}"
        self._messages.append(HumanMessage(content=role_prompt))
        response = self.node.invoke({"messages": self._messages})
        message = response["messages"][-1]
        if not isinstance(message, AIMessage):
            raise TypeError("Scenario node returned a non-AI message.")
        content = message.content
        if not isinstance(content, str):
            content = str(content)
        self._messages.append(AIMessage(content=content))
        transcript.append(
            {
                "role": role,
                "loop_index": loop_index,
                "prompt": prompt,
                "response": content,
            }
        )
        return content

    @staticmethod
    def _parse_findings(payload: str) -> list[Finding]:
        data = json.loads(payload)
        findings = data.get("findings", [])
        return [Finding(**finding) for finding in findings]

    @staticmethod
    def _parse_review_decision(payload: str) -> dict[str, Any]:
        data = json.loads(payload)
        return {
            "approved": bool(data.get("approved")),
            "needs_more_research": bool(data.get("needs_more_research")),
            "blocking_gaps": list(data.get("blocking_gaps", [])),
        }
