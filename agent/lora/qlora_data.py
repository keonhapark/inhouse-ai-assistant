"""QLoRA 학습 예시를 토큰으로 바꿉니다(#545). torch 없이 돌아 agent 시험 환경에서 시험합니다.

생성기(`make_toolcall_data.py`) 한 줄 = system·user·assistant(정답) 세 메시지와 도구 정의입니다. 모델 chat template에
tools를 넘겨 전체를 토큰으로 만들고, 정답(마지막 assistant 메시지) 부분만 손실에 넣습니다(앞부분 labels = -100).
정답 앞부분은 같은 template에 마지막 메시지를 빼고 add_generation_prompt=True로 만든 토큰열이라, 전체 토큰열의
앞부분과 같아야 합니다. 다르면(template이 앞부분을 바꾸는 경우) 그 예시는 쓰지 않고 세어 둡니다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

IGNORE = -100


class ChatTokenizer(Protocol):
    def apply_chat_template(self, conversation: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                            tokenize: bool = True, add_generation_prompt: bool = False,
                            **kwargs: Any) -> list[int]: ...


@dataclass
class Encoded:
    input_ids: list[int]
    labels: list[int]


@dataclass
class Stats:
    used: int = 0
    too_long: int = 0
    prefix_mismatch: int = 0
    target_tokens: list[int] = field(default_factory=list)


def read_rows(path: Path) -> Iterator[dict[str, Any]]:
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def _ids(out: Any) -> list[int]:
    # transformers 판에 따라 list 또는 {"input_ids": [...]}(BatchEncoding)를 돌려줍니다
    if isinstance(out, dict) or hasattr(out, "keys"):
        out = out["input_ids"]
    return list(out)


def encode(row: dict[str, Any], tok: ChatTokenizer, max_len: int, template_kwargs: dict[str, Any]) -> Encoded | str:
    """한 예시를 토큰으로. 쓰지 못하면 이유('too_long', 'prefix_mismatch')를 돌려줍니다."""
    messages, tools = row["messages"], row.get("tools") or None
    full = _ids(tok.apply_chat_template(messages, tools=tools, tokenize=True, add_generation_prompt=False,
                                        **template_kwargs))
    prompt = _ids(tok.apply_chat_template(messages[:-1], tools=tools, tokenize=True, add_generation_prompt=True,
                                          **template_kwargs))
    if full[:len(prompt)] != prompt or len(full) <= len(prompt):
        return "prefix_mismatch"
    if len(full) > max_len:
        return "too_long"
    return Encoded(full, [IGNORE] * len(prompt) + full[len(prompt):])


def encode_all(rows: Iterable[dict[str, Any]], tok: ChatTokenizer, max_len: int,
               template_kwargs: dict[str, Any] | None = None) -> tuple[list[Encoded], Stats]:
    out: list[Encoded] = []
    stats = Stats()
    for row in rows:
        e = encode(row, tok, max_len, template_kwargs or {})
        if isinstance(e, str):
            setattr(stats, e, getattr(stats, e) + 1)
            continue
        stats.used += 1
        stats.target_tokens.append(sum(1 for x in e.labels if x != IGNORE))
        out.append(e)
    return out, stats


def collate(batch: list[Encoded], pad_id: int) -> dict[str, list[list[int]]]:
    """오른쪽 채움. attention_mask는 채운 자리 0, labels는 채운 자리 -100."""
    width = max(len(e.input_ids) for e in batch)
    ids, mask, labels = [], [], []
    for e in batch:
        pad = width - len(e.input_ids)
        ids.append(e.input_ids + [pad_id] * pad)
        mask.append([1] * len(e.input_ids) + [0] * pad)
        labels.append(e.labels + [IGNORE] * pad)
    return {"input_ids": ids, "attention_mask": mask, "labels": labels}


def answer_positions(labels: list[list[int]]) -> list[list[bool]]:
    """다음 토큰이 정답인 자리(True). 자리 t의 logits가 labels[t+1]을 맞히므로 한 칸 당기고 마지막 자리는 False입니다.
    이 자리의 logits만 만들면 어휘(248,320) × 전체 길이 logits를 만들지 않아도 손실이 같습니다(#618)."""
    return [[x != IGNORE for x in row[1:]] + [False] for row in labels]
