"""별칭별 모델 프로필(#595, 결정 0009, contracts/openapi/gateway.yaml `ModelProfile`).

모델마다 다른 실행 설정을 LiteLLM 별칭 표(`litellm/config.yaml`)의 `model_info.profile`에 둡니다.

- `thinking`: 호출 목적별 생각 단계(`plan`·`reroute`·`imageRead`·`ragAnswer`·`incident`). `on`이면 `reasoning_effort: low`,
  `off`이면 `none`, `default`이면 보내지 않음(모델 기본값). YAML에서는 `"on"`·`"off"`에 따옴표를 붙입니다(안 붙이면 불리언).
- `timeoutSeconds`: 그 별칭 호출 한 번의 시간 제한(초)
- `structuredOutput`: response_format 지원 여부(기본 true). false면 gateway가 response_format 요청을 400으로 돌려줍니다
- `vision`: 이미지 입력을 받는 별칭인지(로컬만)

`model_info.evalOnly: true`는 평가에서만 쓰는 별칭입니다. 프로필이 없는 별칭(임베딩 등)은 아래 기본값을 씁니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PURPOSES = ("plan", "reroute", "imageRead", "ragAnswer", "incident")
THINKING = ("on", "off", "default")
EFFORT = {"on": "low", "off": "none", "default": None}
DEFAULT_TIMEOUT_SECONDS = 120


def _thinking(alias: str, raw: Any) -> dict[str, str]:
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - set(PURPOSES):
        raise ValueError(f"{alias}: profile.thinking에는 {', '.join(PURPOSES)}만 씁니다")
    out = {}
    for p in PURPOSES:
        v = raw.get(p, "default")
        if isinstance(v, bool):  # 따옴표 없는 on·off(YAML 1.1 불리언)
            v = "on" if v else "off"
        if v not in THINKING:
            raise ValueError(f"{alias}: profile.thinking.{p}는 on·off·default 중 하나입니다")
        out[p] = v
    return out


def load_model_profiles(config_path: Path) -> list[dict[str, Any]]:
    """별칭 표를 `ModelProfile` 목록으로 읽습니다(설정 순서대로). 값이 틀리면 ValueError로 gateway가 뜨지 않습니다."""
    doc = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    out = []
    for m in doc.get("model_list", []):
        alias, info = m["model_name"], dict(m.get("model_info") or {})
        if info.get("location") not in ("local", "external"):
            raise ValueError(f"LiteLLM 별칭 {alias}에 model_info.location(local|external)이 없습니다")
        raw = dict(info.get("profile") or {})
        extra = set(raw) - {"thinking", "timeoutSeconds", "structuredOutput", "vision"}
        if extra:
            raise ValueError(f"{alias}: profile에 모르는 키 {', '.join(sorted(extra))}")
        timeout = raw.get("timeoutSeconds", DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise ValueError(f"{alias}: profile.timeoutSeconds는 1 이상의 정수입니다")
        vision = bool(raw.get("vision", False))
        if vision and info["location"] != "local":
            raise ValueError(f"{alias}: 이미지 입력(profile.vision)은 로컬 별칭만 받습니다")
        entry = {"alias": alias, "location": info["location"], "model": (m.get("litellm_params") or {}).get("model", ""),
                 "evalOnly": bool(info.get("evalOnly", False)),
                 "profile": {"thinking": _thinking(alias, raw.get("thinking")), "timeoutSeconds": timeout,
                             "structuredOutput": bool(raw.get("structuredOutput", True)), "vision": vision}}
        if info.get("mode"):
            entry["mode"] = info["mode"]
        out.append(entry)
    return out


def effort_for(profile: dict[str, Any], purpose: str) -> str | None:
    """프로필의 호출 목적 값을 보낼 reasoning_effort로 바꿉니다(default면 None)."""
    return EFFORT[profile["profile"]["thinking"][purpose]]
