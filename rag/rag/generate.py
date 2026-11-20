"""생성 문서(docs.yaml `source.type: generated`)를 템플릿과 팩 값으로 만듭니다.

템플릿(`templates/<문서 ID>.md`)에는 회사·부서 이름 같은 팩 고유어를 쓰지 않고 자리표시자를 씁니다.
코어가 업종을 모르게 하려는 것입니다(docs/workflow.md 1절).

자리표시자:
- `{{ company }}`: 회사 이름
- `{{ role:<역할 ID> }}`: 역할 이름
- `{{ role_unit:<역할 ID> }}`: 역할이 권한을 갖는 첫 조직 이름
- `{{ grade:<직급 ID> }}`: 직급 이름
- `{{ employee:<직원 ID> }}`: "이름(소속)"
- `{{ rooms }}`: 회의실 목록(줄마다 "- 이름: N층, 정원 M명")
- `{{ leave_types }}`: 휴가 양식의 휴가 종류 이름(쉼표로 이음)
- `{{ delegation:<키> }}`: org.yaml `delegation_policy` 값. 점으로 안쪽 키를 고릅니다(`wide_scope.period_days_over`)
- `{{ amount:<원> }}`: 금액을 "1,000,000원"처럼 씀

절은 `## <머리>`로 나눕니다. 머리가 "제N조(제목)" 꼴이면 label·heading으로 나눕니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from rag.pack import Pack

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)(?::([A-Za-z0-9_.\-]+))?\s*\}\}")
ARTICLE_HEAD = re.compile(r"^(제\d+조(?:의\d+)?)\s*\((.+)\)\s*$")


class TemplateError(Exception):
    pass


def _by_id(items: list[dict[str, Any]], key: str, what: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == key:
            return item
    raise TemplateError(f"{what} '{key}'를 팩에서 찾지 못했습니다")


def _resolve(name: str, arg: str | None, pack: Pack) -> str:
    org = pack.org
    if name == "company":
        return pack.meta["company"]["name"]
    if name == "role":
        return _by_id(org["roles"], arg, "역할")["name"]
    if name == "role_unit":
        role = _by_id(org["roles"], arg, "역할")
        grant = role.get("grant")
        units = grant.get("units") if isinstance(grant, dict) else None
        if not units:
            raise TemplateError(f"역할 '{arg}'에 조직 권한이 없습니다")
        return _by_id(org["units"], units[0], "조직")["name"]
    if name == "grade":
        return _by_id(org["grades"], arg, "직급")["name"]
    if name == "employee":
        emp = _by_id(pack.employees, arg, "직원")
        unit = _by_id(org["units"], emp["unit_id"], "조직")["name"]
        return f"{emp['name']}({unit})"
    if name == "rooms":
        return "\n".join(f"- {r['name']}: {r['floor']}층, 정원 {r['capacity']}명" for r in pack.rooms)
    if name == "leave_types":
        form = _by_id(pack.forms, "leave", "양식")
        labels = form["fields"]["properties"]["leave_type"]["x-labels"]
        return ", ".join(labels.values())
    if name == "delegation":
        value: Any = org["delegation_policy"]
        for part in (arg or "").split("."):
            if not isinstance(value, dict) or part not in value:
                raise TemplateError(f"delegation_policy에 '{arg}'가 없습니다")
            value = value[part]
        return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else str(value)
    if name == "amount":
        return f"{int(arg or 0):,}원"
    raise TemplateError(f"모르는 자리표시자 '{name}'")


def render_text(template: str, pack: Pack) -> str:
    return PLACEHOLDER.sub(lambda m: _resolve(m.group(1), m.group(2), pack), template)


def split_sections(text: str) -> list[dict[str, Any]]:
    """`## 머리`로 절을 나눕니다. 첫 `##` 앞의 글(제목 줄 제외)은 머리 없는 절이 됩니다."""
    sections: list[dict[str, Any]] = []
    head: str | None = None
    lines: list[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if not body:
            return
        label, heading = head, None
        if head and (m := ARTICLE_HEAD.match(head)):
            label, heading = m.group(1), m.group(2)
        elif head:
            label, heading = None, head
        sections.append({"label": label, "heading": heading, "text": body})

    for line in text.splitlines():
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            flush()
            head, lines = line[3:].strip(), []
        else:
            lines.append(line)
    flush()
    return sections


def render_document(doc_id: str, pack: Pack, template_dir: Path = TEMPLATE_DIR) -> list[dict[str, Any]]:
    path = template_dir / f"{doc_id}.md"
    if not path.exists():
        raise TemplateError(f"{doc_id}: 템플릿 {path}가 없습니다")
    return split_sections(render_text(path.read_text(encoding="utf-8"), pack))
