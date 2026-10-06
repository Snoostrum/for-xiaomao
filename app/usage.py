"""用量小账本:每次问模型花了多少 token,记在本机(data/usage.jsonl),给「成本可见」用。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _usage_path(data_dir: Path) -> Path:
    return data_dir / "usage.jsonl"


def record_usage(data_dir: Path, purpose: str, model: str, usage: dict | None) -> None:
    """追加一条用量。平台没回 usage 也记一笔(次数照算、token 记 0)——别让账本漏次。"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "purpose": purpose,
        "model": model,
        "prompt_tokens": int((usage or {}).get("prompt_tokens") or 0),
        "completion_tokens": int((usage or {}).get("completion_tokens") or 0),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with _usage_path(data_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:  # 记账失败不能把正事搞砸
        log.warning("用量记录失败:%s", e)


def usage_totals(data_dir: Path) -> dict:
    """汇总全本账。坏行跳过,不因一行脏数据全盘失败。"""
    calls = prompt = completion = 0
    p = _usage_path(data_dir)
    if p.exists():
        # errors="replace":账本里混进非 UTF-8 字节(手改、磁盘花)时把坏字节替掉继续读——
        # 替完还不是 JSON 的行下面照跳,不能让一个坏字节把整本账(和 /api/usage)带崩
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue  # 合法 JSON 但不是对象(比如一行 123):跳过,别在 .get 上炸
            calls += 1
            try:
                prompt_tokens = int(e.get("prompt_tokens") or 0)
                completion_tokens = int(e.get("completion_tokens") or 0)
            except (ValueError, TypeError):
                continue  # token 数字是脏的:次数照算(账本不漏次),数字不计
            prompt += prompt_tokens
            completion += completion_tokens
    return {"calls": calls, "prompt_tokens": prompt, "completion_tokens": completion}
