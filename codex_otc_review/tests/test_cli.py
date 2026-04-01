from pathlib import Path

import codex_otc_review.runner as runner_module


def test_main_builds_codex_node_from_cli_args(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _FakeNode:
        def __init__(self, **kwargs) -> None:
            captured["node_kwargs"] = kwargs

    class _FakeScenarioRunner:
        def __init__(self, *, config, node) -> None:
            captured["config"] = config
            captured["node"] = node

        def run(self):
            captured["ran"] = True
            return None

    monkeypatch.setattr(runner_module, "CodexAppServerNode", _FakeNode)
    monkeypatch.setattr(runner_module, "ScenarioRunner", _FakeScenarioRunner)

    exit_code = runner_module.main(
        [
            "--project",
            "/home/vlad/Projects/otc-backend",
            "--focus",
            "tx-controller",
            "--max-loops",
            "3",
            "--model",
            "gpt-5-codex",
            "--out-dir",
            str(tmp_path),
            "--approval-policy",
            "never",
            "--sandbox-policy",
            "workspace-write",
        ]
    )

    assert exit_code == 0
    assert captured["ran"] is True
    assert captured["config"].project == Path("/home/vlad/Projects/otc-backend")
    assert captured["node_kwargs"] == {
        "cwd": "/home/vlad/Projects/otc-backend",
        "model": "gpt-5-codex",
        "approval_policy": "never",
        "sandbox_policy": "workspace-write",
        "client_info": {"name": "codex-otc-review", "version": "0.1.0"},
    }
