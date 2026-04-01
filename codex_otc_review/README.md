# Codex OTC Review

Runnable multi-role review scenario for validating `CodexAppServerNode` against a
real project checkout.

## What It Does

The runner executes a read-only multi-role review flow through a real
`CodexAppServerNode`:

- `orchestrator` sets the scope
- `researcher` inspects the target repository and proposes findings
- `reviewer` critiques the findings and can request another pass
- `orchestrator` emits the final markdown report

Artifacts written under `--out-dir`:

- `report.md`
- `findings.json`
- `transcript.jsonl`

## Requirements

- a working `codex` CLI installation
- authenticated Codex access
- local checkout of the target repository
- Python `<3.15`

## Recommended Run Environment

The local machine in this workspace already needed Python `3.14` for `langgraph`
dependencies, so the most reliable way to run the scenario is:

```bash
cd /home/vlad/Projects/langgraph/codex_otc_review
nix shell nixpkgs#python314 nixpkgs#uv --command \
  env UV_PROJECT_ENVIRONMENT=.venv314 UV_PYTHON=python \
  uv run python -m codex_otc_review.runner \
    --project /home/vlad/Projects/otc-backend \
    --focus tx-controller \
    --max-loops 2 \
    --model gpt-5 \
    --out-dir ./artifacts/otc-backend-review
```

## Alternative Run

If you already have a supported local Python:

```bash
cd /home/vlad/Projects/langgraph/codex_otc_review
uv run python -m codex_otc_review.runner \
  --project /home/vlad/Projects/otc-backend \
  --focus tx-controller \
  --max-loops 2 \
  --model gpt-5 \
  --out-dir ./artifacts/otc-backend-review
```

## Test The Package

```bash
cd /home/vlad/Projects/langgraph/codex_otc_review
nix shell nixpkgs#python314 nixpkgs#uv --command \
  env UV_PROJECT_ENVIRONMENT=.venv314 UV_PYTHON=python \
  uv run pytest tests -q
```
