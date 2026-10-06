from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path

log = logging.getLogger(__name__)

_STRIP_FIELDS = ("provider", "base_url", "api_key", "model", "vision_model", "download_dir")


@dataclass
class Config:
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    vision_model: str = ""  # 看扫描页用的模型;留空 = 和主模型相同
    download_dir: str = ""


def config_path(data_dir: Path) -> Path:
    return data_dir / "config.json"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "…" + key[-4:]


def _as_str(v: object) -> str:
    return "" if v is None else str(v)


def _backup_broken(p: Path) -> Path:
    n = 1
    while True:
        candidate = p.with_name(f"{p.name}.broken{n}")
        if not candidate.exists():
            return candidate
        n += 1


def load_config(data_dir: Path) -> Config:
    p = config_path(data_dir)
    if not p.exists():
        return Config()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config.json 顶层不是对象")
        cfg = Config(**{f.name: _as_str(raw.get(f.name)) for f in fields(Config)})
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        backup = _backup_broken(p)
        p.replace(backup)
        log.warning("config.json 读取失败(%s),已备份到 %s,按默认值继续", e, backup.name)
        return Config()
    for name in _STRIP_FIELDS:
        setattr(cfg, name, getattr(cfg, name).strip())
    return cfg


def save_config(data_dir: Path, cfg: Config) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in _STRIP_FIELDS:
        setattr(cfg, name, getattr(cfg, name).strip())
    p = config_path(data_dir)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
