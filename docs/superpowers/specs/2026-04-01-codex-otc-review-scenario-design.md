# Codex OTC Review Scenario Design

**Date:** 2026-04-01

**Status:** Approved in chat, pending written spec review

## Goal

Add a runnable mini-package that exercises the real `CodexAppServerNode`
against a real project checkout, starting with
`/home/vlad/Projects/otc-backend`.

The package should let a user run one command and get:

- a coordinated multi-role review scenario
- explicit communication between roles
- one or more review-loop iterations
- a persisted final report and raw transcript

The package is intended as a realistic end-to-end scenario for validating the
`CodexAppServerNode` implementation on a non-trivial repository, not as a
synthetic unit test.

## Scope

This design covers a standalone Python mini-package stored in the `langgraph`
repository.

It does not cover:

- modifying the target repository under review
- opening pull requests or applying fixes automatically
- integrating LangGraph runtime code into `otc-backend`
- CI-backed tests that require a live `codex app-server`
- generalized multi-project orchestration beyond a first local CLI

## Why A Standalone Mini-Package

The target project is a separate mixed-language monorepo and the user wants a
scenario they can run manually against their own checkout.

Keeping the scenario outside `otc-backend` has three advantages:

1. No production or documentation churn in the reviewed project.
2. The scenario can import the freshly implemented local
   `langgraph.prebuilt.CodexAppServerNode`.
3. Iteration on prompts, reporting, and review-loop behavior stays isolated
   from the target system.

## Package Shape

Create a small package, tentatively named `codex_otc_review`, with focused
modules:

- `codex_otc_review/runner.py`
  - CLI entrypoint
  - parses arguments
  - wires together node, loop, and output paths
- `codex_otc_review/config.py`
  - dataclass or typed config loader
  - default focus areas, loop counts, and path handling
- `codex_otc_review/prompts.py`
  - role prompts and scenario framing
  - orchestrator, researcher, reviewer prompt builders
- `codex_otc_review/reporting.py`
  - writes `report.md`, `findings.json`, and `transcript.jsonl`
- `codex_otc_review/__init__.py`
  - minimal package marker or exported runner helpers
- `codex_otc_review/README.md`
  - installation and run instructions
- `codex_otc_review/pyproject.toml`
  - minimal runner environment for `uv`

The package should live in the `langgraph` repo, not inside `libs/prebuilt`,
because it is an operational scenario and manual tool, not a reusable prebuilt
runtime component.

## Runtime Model

The scenario uses one long-lived `CodexAppServerNode` instance pointed at the
target project directory.

### Process model

- one local Python process for the runner
- one long-lived `codex app-server` subprocess managed by
  `CodexAppServerNode`
- one reused Codex thread across turns

### Agent model

The scenario simulates multiple collaborating roles through explicit turn
framing rather than multiple Python-side node instances:

- `orchestrator`
  - chooses focus
  - decides whether another review loop is needed
  - produces the final synthesis
- `researcher`
  - inspects repository areas
  - proposes findings with evidence
- `reviewer`
  - critiques the researcher output
  - looks for missed risks, weak claims, and missing evidence

This keeps the runtime simple while still validating role-to-role
communication, long-lived thread reuse, and iterative review behavior.

## User-Facing CLI

The runner should accept at least:

```text
python -m codex_otc_review.runner \
  --project /home/vlad/Projects/otc-backend \
  --focus tx-controller \
  --max-loops 2 \
  --model gpt-5 \
  --out-dir ./artifacts/otc-review
```

Required argument:

- `--project`

Optional arguments:

- `--focus`
- `--max-loops`
- `--model`
- `--out-dir`
- `--approval-policy`
- `--sandbox-policy`

Defaults should be chosen so a user can run the tool with just `--project`.

## Scenario Flow

### 1. Bootstrap

- validate the target project path exists
- create output directory
- initialize `CodexAppServerNode` with the target project as `cwd`

### 2. Orchestrator kickoff

The first turn should ask the orchestrator to:

- identify the repository shape
- select the most relevant code area for the requested focus
- define review objectives

### 3. Research pass

The next turn should ask the researcher to:

- inspect the selected code and surrounding docs/tests
- produce findings with evidence and file references
- separate confirmed risks from weaker hypotheses

### 4. Review pass

The reviewer then:

- audits the researcher output
- challenges unsupported claims
- identifies missed edge cases or missing evidence
- requests another pass if quality is insufficient

### 5. Loop control

The orchestrator decides whether to:

- stop and publish findings
- ask the researcher for one more pass guided by reviewer feedback

The first version should allow a configurable fixed upper bound, for example
`max_loops=2` or `3`.

### 6. Finalization

The runner writes artifacts and exits without modifying the target project.

## Review Loop Contract

The scenario should make the role communication explicit and machine-readable.

Each turn record should include:

- `role`
- `loop_index`
- `prompt`
- `response`
- `timestamp`

Reviewer output should include a structured recommendation:

- `approved`
- `needs_more_research`
- `blocking_gaps`

The orchestrator should interpret this recommendation instead of trying to infer
loop control from free text alone.

## Output Contract

The package writes three artifacts under `out_dir`:

### `report.md`

Human-readable final report containing:

- executive summary
- findings ordered by severity
- reviewer disagreements or uncertainty notes
- residual risks
- suggested next checks

### `findings.json`

Structured findings list. Each finding contains:

- `id`
- `severity`
- `title`
- `evidence`
- `file_refs`
- `why_it_matters`
- `suggested_follow_up`

### `transcript.jsonl`

Append-only event log with every role prompt and response in order.

## Prompting Strategy

Prompts should bias strongly toward code review, not implementation.

Common instructions for all roles:

- read-only analysis only
- do not modify files
- do not propose speculative bugs without evidence
- cite concrete file paths when possible
- prefer concise, technical output

Role-specific differences:

- orchestrator: scope control and synthesis
- researcher: evidence gathering and candidate findings
- reviewer: adversarial quality gate

## Safety

The scenario should run with conservative execution settings:

- target `cwd` is the reviewed project path
- default `sandbox_policy` is `workspace-write`
- prompt-level instructions explicitly forbid repository edits

If the resulting transcript shows the model entering an edit-oriented path, the
runner should treat that as a scenario failure and capture it in the report.

The first version should not attempt to enforce edit prevention at the protocol
layer beyond these configuration and prompt constraints.

## File Plan

Expected additions under the `langgraph` repository root:

- Create: `codex_otc_review/pyproject.toml`
- Create: `codex_otc_review/README.md`
- Create: `codex_otc_review/codex_otc_review/__init__.py`
- Create: `codex_otc_review/codex_otc_review/config.py`
- Create: `codex_otc_review/codex_otc_review/prompts.py`
- Create: `codex_otc_review/codex_otc_review/reporting.py`
- Create: `codex_otc_review/codex_otc_review/runner.py`

Optional supporting additions if needed:

- Create: `codex_otc_review/.gitignore`
- Create: `codex_otc_review/examples/`

## Validation Strategy

Because this package targets a live local `codex app-server`, validation should
focus on:

1. importability of the mini-package
2. CLI argument validation
3. artifact writing behavior for deterministic local helpers
4. one manual smoke run against `/home/vlad/Projects/otc-backend`

The first version does not need CI to run the live Codex session.

## Implementation Constraints

- keep the package small and self-contained
- do not add heavyweight dependencies if stdlib is enough
- import the local `langgraph.prebuilt.CodexAppServerNode`
- do not modify the reviewed project
- optimize for a user-run manual scenario, not library abstraction purity

## Open Questions

None at this stage. The user selected:

- a real project scenario instead of a synthetic test
- a standalone mini-package rather than a single loose script
- explicit review loops and communication between roles
- persisted artifacts for manual inspection
- `/home/vlad/Projects/otc-backend` as the initial target project
