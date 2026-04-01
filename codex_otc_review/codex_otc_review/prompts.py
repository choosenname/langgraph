"""Prompt builders for scenario roles."""

from __future__ import annotations


def build_orchestrator_prompt(project_path: str, focus: str, max_loops: int) -> str:
    """Build the orchestrator kickoff prompt."""

    return (
        "You are the orchestrator for a read-only code review scenario.\n"
        f"Project: {project_path}\n"
        f"Focus: {focus}\n"
        f"Max loops: {max_loops}\n"
        "Set the review scope, keep the team aligned, and never edit files."
    )


def build_researcher_prompt(project_path: str, focus: str, feedback: str | None) -> str:
    """Build the researcher prompt."""

    prompt = [
        "You are the researcher in a read-only code review scenario.",
        f"Project: {project_path}",
        f"Focus: {focus}",
        "Inspect the relevant code and report evidence-backed findings only.",
    ]
    if feedback:
        prompt.append(f"Reviewer feedback to address: {feedback}")
    return "\n".join(prompt)


def build_reviewer_prompt(project_path: str, focus: str, researcher_output: str) -> str:
    """Build the reviewer prompt."""

    return (
        "You are the reviewer in a read-only code review scenario.\n"
        f"Project: {project_path}\n"
        f"Focus: {focus}\n"
        "Critique the researcher output, identify missing evidence, and return a"
        " recommendation of approved or needs_more_research.\n\n"
        f"Researcher output:\n{researcher_output}"
    )
