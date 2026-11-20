"""사내 용어 사전으로 외부 요청의 기밀 여부를 판정합니다.

사전은 팩의 `glossary.yaml`입니다(contracts/pack/pack.schema.json, #62). 파일이 없으면 판정하지 않습니다.
용어마다 action이 있습니다: local_only(외부 요청을 로컬 모델로 돌림), block(요청 차단). 둘 다 걸리면 block이 이깁니다.
기록에는 용어 자체를 남기지 않고 개수와 action만 남깁니다(용어가 기밀일 수 있음).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ACTIONS = ("local_only", "block")


@dataclass(frozen=True)
class Term:
    words: tuple[str, ...]
    level: str
    action: str
    reason: str


@dataclass(frozen=True)
class Verdict:
    action: str          # local_only | block
    hits: int
    reason: str


class Glossary:
    def __init__(self, terms: list[Term]):
        self.terms = terms

    @classmethod
    def from_doc(cls, doc: dict[str, Any] | None) -> Glossary:
        terms = []
        for t in (doc or {}).get("terms", []):
            action = t.get("action", "local_only")
            if action not in ACTIONS:
                raise ValueError(f"glossary action은 {ACTIONS} 중 하나여야 합니다: {action}")
            words = tuple(w.casefold() for w in [t["term"], *t.get("aliases", [])] if w)
            terms.append(Term(words, t.get("level", "confidential"), action,
                              t.get("reason", "사내 기밀 용어가 들어 있습니다")))
        return cls(terms)

    @classmethod
    def load(cls, pack_dir: Path) -> Glossary:
        p = pack_dir / "glossary.yaml"
        if not p.exists():
            return cls([])
        return cls.from_doc(yaml.safe_load(p.read_text(encoding="utf-8")))

    def check(self, body: dict[str, Any]) -> Verdict | None:
        if not self.terms:
            return None
        text = _texts(body).casefold()
        hit = [t for t in self.terms if any(w in text for w in t.words)]
        if not hit:
            return None
        worst = next((t for t in hit if t.action == "block"), hit[0])
        return Verdict(worst.action, len(hit), worst.reason)


def _texts(body: dict[str, Any]) -> str:
    """messages와 tools 안의 모든 문자열(내용, 도구 호출 인자, 도구 정의)을 한 덩어리로 모읍니다."""
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    walk(body.get("messages", []))
    walk(body.get("tools", []))
    return "\n".join(out)
