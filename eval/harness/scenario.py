"""시나리오 읽기와 검사.

계약 스키마(contracts/eval/scenario.schema.json)로 형식을 보고, 스키마로 적기 어려운 규칙을 더 봅니다.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from harness.paths import MCP_TOOLS, SCENARIO_SCHEMA


class ScenarioError(ValueError):
    """시나리오 파일이 계약이나 추가 규칙을 어김."""

    def __init__(self, path: str, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: " + "; ".join(problems))


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(SCENARIO_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@cache
def known_tools() -> frozenset[str]:
    data = json.loads(MCP_TOOLS.read_text(encoding="utf-8"))
    return frozenset(t["name"] for t in data["tools"])


def _extra_rules(s: dict[str, Any]) -> list[str]:
    """스키마 밖의 규칙. 판정이 뜻대로 되려면 필요한 것만 봅니다."""
    problems: list[str] = []
    expect = s.get("expect", {})
    if s["kind"] == "normal":
        if "concernType" in s:
            problems.append("정상 시나리오에 concernType이 있습니다")
        if expect.get("outcome") == "blocked":
            problems.append("정상 시나리오의 expect.outcome이 blocked입니다")
    else:
        if "reactive" in s:
            problems.append("reactive는 정상 시나리오에만 씁니다")
        if expect.get("outcome") == "completed":
            problems.append("우려 시나리오의 expect.outcome이 completed입니다")
        if not (expect.get("markers") or expect.get("forbiddenTools") or expect.get("dbAssertions")
                or expect.get("externalAllowed") is False):
            problems.append("우려 시나리오에 사고 판정 기준(markers, forbiddenTools, dbAssertions, "
                            "externalAllowed=false)이 하나도 없습니다")
    tools = known_tools()
    named = list(expect.get("forbiddenTools", [])) + list(expect.get("requiredTools", []))
    named += [r["tool"] for r in s.get("riskLabels", [])]
    named += [a["tool"] for a in expect.get("approvable", [])]
    for t in named:
        if t not in tools:
            problems.append(f"계약에 없는 도구 이름: {t}")
    overlap = set(expect.get("forbiddenTools", [])) & set(expect.get("requiredTools", []))
    if overlap:
        problems.append(f"금지 도구와 필수 도구가 겹칩니다: {sorted(overlap)}")
    saved: set[str] = set()
    for i, step in enumerate(s.get("setup", [])):
        for ref in _refs(step):
            if ref not in saved:
                problems.append(f"setup[{i}]이 앞에서 저장하지 않은 ${{{ref}}}를 씁니다")
        if "saveAs" in step:
            saved.add(step["saveAs"])
    for i, a in enumerate(expect.get("dbAssertions", [])):
        for ref in _refs(a):
            if ref not in saved:
                problems.append(f"dbAssertions[{i}]가 setup에서 저장하지 않은 ${{{ref}}}를 씁니다")
    for i, a in enumerate(expect.get("approvable", [])):
        for ref in _refs(a):
            if ref not in saved:
                problems.append(f"approvable[{i}]가 setup에서 저장하지 않은 ${{{ref}}}를 씁니다")
    return problems


_REF = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def _refs(obj: Any) -> set[str]:
    return set(_REF.findall(json.dumps(obj, ensure_ascii=False)))


def has_document_injection(scenario: dict[str, Any]) -> bool:
    """문서형 주입 시나리오인지. 주입 문서는 rag 주입 파일(RAG_EXTRA_DOCS)로만 심깁니다."""
    return any(i.get("where") == "document" for i in scenario.get("injectedContent", []))


def substitute(obj: Any, variables: dict[str, str]) -> Any:
    """문자열 안의 ${이름}을 setup에서 저장한 값으로 바꿉니다. 없는 이름이면 KeyError."""
    if isinstance(obj, str):
        return _REF.sub(lambda m: variables[m.group(1)], obj)
    if isinstance(obj, list):
        return [substitute(x, variables) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, variables) for k, v in obj.items()}
    return obj


def validate_scenario(data: Any, path: str = "<memory>") -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ScenarioError(path, ["최상위가 객체가 아닙니다"])
    errors = sorted(_validator().iter_errors(data), key=lambda e: list(e.absolute_path))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '(최상위)'}: {e.message}" for e in errors]
    if not problems:
        problems = _extra_rules(data)
    if problems:
        raise ScenarioError(path, problems)
    return data


def _read(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) if path.suffix in (".yaml", ".yml") else json.loads(text)


def load_scenario(path: Path) -> dict[str, Any]:
    return validate_scenario(_read(path), str(path))


def scenario_paths(directory: Path) -> list[Path]:
    """load_scenarios가 읽는 파일 목록입니다."""
    return sorted(p for p in directory.rglob("*") if p.suffix in (".json", ".yaml", ".yml"))


def load_scenarios(directory: Path) -> list[dict[str, Any]]:
    """폴더 아래 시나리오를 모두 읽습니다. 파일 하나에 시나리오 하나(객체)나 여러 개(목록)를 둡니다.

    하나라도 틀리면 전부 모아 ScenarioError로 알립니다.
    """
    files = scenario_paths(directory)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    ids: dict[str, str] = {}
    for f in files:
        data = _read(f)
        items = data if isinstance(data, list) else [data]
        for i, item in enumerate(items):
            where = f"{f.name}[{i}]" if isinstance(data, list) else f.name
            try:
                s = validate_scenario(item, where)
            except ScenarioError as e:
                problems.extend(f"{where}: {p}" for p in e.problems)
                continue
            if s["id"] in ids:
                problems.append(f"{where}: id {s['id']}가 {ids[s['id']]}와 겹칩니다")
                continue
            ids[s["id"]] = where
            out.append(s)
    if problems:
        raise ScenarioError(str(directory), problems)
    return out
