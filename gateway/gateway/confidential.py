"""사내 용어 사전으로 외부 요청의 기밀 여부를 판정합니다.

사전은 팩의 `glossary.yaml`입니다(contracts/pack/pack.schema.json, #62). 파일이 없으면 판정하지 않습니다.
용어마다 action이 있습니다: local_only(외부 요청을 로컬 모델로 돌림), block(요청 차단). 둘 다 걸리면 block이 이깁니다.
기록에는 용어 자체를 남기지 않고 개수와 action만 남깁니다(용어가 기밀일 수 있음).

업무 주제(`topics`, #304)는 정규식으로 대화 내용만 봅니다: system이 아닌 메시지의 content와 도구 호출 인자.
시스템 프롬프트와 도구 정의는 보지 않습니다. 에이전트 설명·도구 설명에 주제어(예: 휴가)가 있어 모든 요청이 걸리는 것을 막습니다.
입구 라우터가 인사 요청을 외부 허용 에이전트로 잘못 보내도 출구에서 로컬로 돌리는 두 번째 방어선입니다(#308).
기록에는 주제 id만 남깁니다.
"""

from __future__ import annotations

import json
import re
import unicodedata
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
class Topic:
    id: str
    action: str
    reason: str
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Verdict:
    action: str          # local_only | block
    hits: int            # 걸린 용어 수
    reason: str
    topics: tuple[str, ...] = ()   # 걸린 업무 주제 id


class Glossary:
    def __init__(self, terms: list[Term], topics: list[Topic] | None = None):
        self.terms = terms
        self.topics = topics or []

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
        topics = []
        for t in (doc or {}).get("topics", []):
            if t.get("action") not in ACTIONS:
                raise ValueError(f"glossary topics action은 {ACTIONS} 중 하나여야 합니다: {t.get('action')}")
            topics.append(Topic(t["id"], t["action"], t.get("reason", "사내 모델로만 다루는 업무 정보가 들어 있습니다"),
                                tuple(re.compile(p, re.IGNORECASE) for p in t["patterns"])))
        return cls(terms, topics)

    @classmethod
    def load(cls, pack_dir: Path) -> Glossary:
        p = pack_dir / "glossary.yaml"
        if not p.exists():
            return cls([])
        return cls.from_doc(yaml.safe_load(p.read_text(encoding="utf-8")))

    def check(self, body: dict[str, Any]) -> Verdict | None:
        hit: list[Term] = []
        if self.terms:
            text = _texts(body).casefold()
            hit = [t for t in self.terms if any(w in text for w in t.words)]
        topic_hit: list[Topic] = []
        if self.topics:
            convo = _conversation_texts(body)
            topic_hit = [t for t in self.topics if any(p.search(convo) for p in t.patterns)]
        if not hit and not topic_hit:
            return None
        found: list[Term | Topic] = [*hit, *topic_hit]
        worst = next((t for t in found if t.action == "block"), found[0])
        return Verdict(worst.action, len(hit), worst.reason, tuple(t.id for t in topic_hit))


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


def _conversation_texts(body: dict[str, Any]) -> str:
    """system이 아닌 메시지 안의 모든 문자열(content, 도구 호출 인자, 레거시 function_call 등)을 모읍니다.

    도구 정의(`tools`)와 system 메시지는 보지 않습니다. JSON 문자열(도구 인자·결과)은 풀어서 다시 써 `\\uXXXX`
    이스케이프를 없애고, 한글은 NFC로 맞춥니다(자모로 나뉜 NFD 입력도 걸리게).
    """
    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            out.append(_unescaped(node))
        elif isinstance(node, list):
            for x in node:
                walk(x)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)

    for m in body.get("messages", []):
        if isinstance(m, dict) and m.get("role") != "system":
            walk({k: v for k, v in m.items() if k != "role"})
    return unicodedata.normalize("NFC", "\n".join(out))


def _unescaped(text: str) -> str:
    if "\\u" not in text:
        return text
    try:
        return json.dumps(json.loads(text), ensure_ascii=False)
    except ValueError:
        return text
