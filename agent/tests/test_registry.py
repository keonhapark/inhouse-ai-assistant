from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from agent_runtime.registry import Registry, RegistryError, Requester, grant_matches
from tests.conftest import PACK_DIR


def test_manufacturing_pack_loads_stage1_agents(registry: Registry) -> None:
    assert registry.pack_id == "manufacturing"
    assert [a.id for a in registry.agents] == ["assistant", "hr"]
    assert registry.fallback.id == "assistant"
    hr = registry.get("hr")
    assert hr.model_policy == "local_only"
    assert "휴가" in hr.keywords
    assert "leave_request" in hr.tools


def _copy_pack(tmp_path: Path) -> Path:
    dst = tmp_path / "pack"
    shutil.copytree(PACK_DIR, dst)
    return dst


def _edit_agents(pack: Path, fn) -> None:
    path = pack / "agents.yaml"
    doc = yaml.safe_load(path.read_text("utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), "utf-8")


def test_agents_of_later_stage_are_not_enabled(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)

    def add_later(doc):
        later = dict(doc["agents"][1], id="later", stage=3)
        doc["agents"].append(later)

    _edit_agents(pack, add_later)
    reg = Registry.load(pack)
    assert not reg.has("later")


def test_default_stage_follows_pack_yaml() -> None:
    reg = Registry.load(PACK_DIR)
    assert reg.pack_stage == 2 and reg.has("finance") and reg.has("procurement")


def test_fallback_agent_must_be_enabled(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    _edit_agents(pack, lambda doc: doc.update(fallback_agent="missing"))
    with pytest.raises(RegistryError, match="fallback_agent"):
        Registry.load(pack)


def test_missing_registry_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        Registry.load(tmp_path)


@pytest.mark.parametrize(
    ("grant", "requester", "expected"),
    [
        ("all", Requester("E1", "sales", "staff", ()), True),
        ({"roles": ["employee"]}, Requester("E1", "sales", "staff", ("employee",)), True),
        ({"roles": ["hr_staff"]}, Requester("E1", "sales", "staff", ("employee",)), False),
        ({"units": ["hr"]}, Requester("E1", "hr", "staff", ()), True),
        # 상위 단위에 준 권한은 하위 단위로 퍼지지 않습니다(가짜 erp와 같은 규칙).
        ({"units": ["mgmt"]}, Requester("E1", "hr", "staff", ()), False),
        ({"grades": ["ceo"]}, Requester("E1", "ceo-office", "ceo", ()), True),
        ({"units": ["hr"], "grades": ["ceo"]}, Requester("E1", "sales", "staff", ()), False),
        ("unknown", Requester("E1", "sales", "staff", ("employee",)), False),
    ],
)
def test_grant_matches(grant, requester: Requester, expected: bool) -> None:
    assert grant_matches(grant, requester) is expected


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda doc: doc["agents"][0]["model_policy"].update(mode="local"), "형식"),
        (lambda doc: doc["agents"][0].pop("callable_by"), "형식"),
        (lambda doc: doc["agents"].append(dict(doc["agents"][1])), "겹칩니다"),
    ],
)
def test_malformed_registry_is_a_registry_error(tmp_path: Path, edit, match: str) -> None:
    pack = _copy_pack(tmp_path)
    _edit_agents(pack, edit)
    with pytest.raises(RegistryError, match=match):
        Registry.load(pack)
