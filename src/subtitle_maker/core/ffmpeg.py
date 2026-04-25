from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """执行外部命令并返回退出码、标准输出和标准错误。"""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cmd_checked(cmd: List[str], cwd: Optional[Path] = None) -> None:
    """执行命令；失败时保留 stdout/stderr 并抛出异常。"""
    code, out, err = run_cmd(cmd, cwd=cwd)
    if code != 0:
        raise RuntimeError(f"command failed ({code}): {' '.join(cmd)}\n{out}\n{err}")


def run_cmd_stream(cmd: List[str], cwd: Optional[Path] = None) -> int:
    """流式执行命令，并把合并后的输出直接打印到当前终端。"""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip())
    return proc.wait()

