"""업종 팩 읽기. 코어는 업종을 모르므로 조직·문서 목록은 모두 팩에서 읽습니다."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def pack_dir(name: str | None = None) -> Path:
    """`RAG_PACK_DIR`가 있으면 그 경로, 없으면 저장소의 `packs/<RAG_PACK>`(기본 manufacturing)."""
    if explicit := os.environ.get("RAG_PACK_DIR"):
        return Path(explicit)
    return REPO_ROOT / "packs" / (name or os.environ.get("RAG_PACK", "manufacturing"))


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


@dataclass(frozen=True)
class Pack:
    root: Path

    @cached_property
    def meta(self) -> dict[str, Any]:
        return _load(self.root / "pack.yaml")

    @cached_property
    def org(self) -> dict[str, Any]:
        return _load(self.root / "org.yaml")

    @cached_property
    def forms(self) -> list[dict[str, Any]]:
        return _load(self.root / "forms.yaml")["forms"]

    @cached_property
    def documents(self) -> list[dict[str, Any]]:
        return _load(self.root / "docs.yaml")["documents"]

    @cached_property
    def employees(self) -> list[dict[str, Any]]:
        return _load(self.root / "fixtures" / "employees.json")["employees"]

    @cached_property
    def rooms(self) -> list[dict[str, Any]]:
        return _load(self.root / "fixtures" / "rooms.json")["rooms"]


def load_pack(name: str | None = None) -> Pack:
    return Pack(pack_dir(name))
