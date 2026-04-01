from pathlib import Path

from codex_otc_review.config import parse_args, parse_config


def test_parse_config_defaults() -> None:
    args = parse_args(["--project", "/tmp/project"])

    config = parse_config(args)

    assert config.project == Path("/tmp/project")
    assert config.focus == "architecture"
    assert config.max_loops == 2
    assert config.model == "gpt-5"
    assert config.out_dir == Path("artifacts/codex-otc-review")
    assert config.approval_policy == "on-request"
    assert config.sandbox_policy == "workspace-write"
