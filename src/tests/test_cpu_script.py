"""Regressions for selecting and authorizing the CPU remediation target."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kill_target_process.sh"


def _run_with_truncated_top(tmp_path: Path, process_name: str) -> tuple[subprocess.CompletedProcess, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    top = fake_bin / "top"
    top.write_text(
        "#!/bin/sh\nprintf ' 424242 root 20 0 0 0 0 R 100.0 0.0 0:01.00 stress-+\\n'\n",
        encoding="utf-8",
    )
    top.chmod(0o755)
    ps = fake_bin / "ps"
    ps.write_text("#!/bin/sh\nprintf '%s\\n' \"$FAKE_PROCESS_NAME\"\n", encoding="utf-8")
    ps.chmod(0o755)

    kill_log = tmp_path / "kill.log"
    bash_env = tmp_path / "bash_env"
    bash_env.write_text(
        "kill() { printf '%s\\n' \"$*\" >> \"$KILL_LOG\"; "
        "[ \"$1\" != -0 ]; }\n",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "BASH_ENV": str(bash_env),
        "KILL_LOG": str(kill_log),
        "FAKE_PROCESS_NAME": process_name,
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "stress-ng,stress,stress-ng-cpu"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=env,
    )
    return result, kill_log.read_text(encoding="utf-8") if kill_log.exists() else ""


def test_cpu_script_uses_full_process_name_when_top_truncates_it(tmp_path):
    result, kill_calls = _run_with_truncated_top(tmp_path, "stress-ng-cpu")

    assert result.returncode == 0, result.stderr
    assert "encerrando stress-ng-cpu (pid 424242" in result.stdout
    assert "-TERM 424242" in kill_calls


def test_cpu_script_still_refuses_non_allowlisted_process(tmp_path):
    result, kill_calls = _run_with_truncated_top(tmp_path, "postgres")

    assert result.returncode == 2
    assert "candidato 'postgres'" in result.stderr
    assert kill_calls == ""
