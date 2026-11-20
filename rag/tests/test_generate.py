import pytest

from rag.generate import TemplateError, render_text, split_sections
from rag.pack import load_pack


@pytest.fixture(scope="module")
def pack():
    return load_pack()


def test_자리표시자를_팩_값으로_채운다(pack):
    org = pack.org
    hr_role = next(r for r in org["roles"] if r["id"] == "hr_staff")
    hr_unit = next(u for u in org["units"] if u["id"] == hr_role["grant"]["units"][0])
    out = render_text("{{ company }}/{{ role:hr_staff }}/{{ role_unit:hr_staff }}/{{ amount:1500000 }}", pack)
    assert out == f"{pack.meta['company']['name']}/{hr_role['name']}/{hr_unit['name']}/1,500,000원"


def test_대결_정책은_점으로_안쪽_키를_고른다(pack):
    policy = pack.org["delegation_policy"]
    out = render_text("{{ delegation:max_period_days }} {{ delegation:wide_scope.max_amount_over }}", pack)
    assert out == f"{policy['max_period_days']} {policy['wide_scope']['max_amount_over']:,}"


def test_직원은_이름과_소속으로_쓴다(pack):
    emp = pack.employees[0]
    unit = next(u for u in pack.org["units"] if u["id"] == emp["unit_id"])
    assert render_text(f"{{{{ employee:{emp['id']} }}}}", pack) == f"{emp['name']}({unit['name']})"


@pytest.mark.parametrize(
    "bad", ["{{ nope }}", "{{ role:no_such_role }}", "{{ delegation:no.key }}", "{{ amount }}", "{{ amount:abc }}"]
)
def test_모르는_자리표시자나_없는_값은_실패한다(pack, bad):
    with pytest.raises(TemplateError):
        render_text(bad, pack)


def test_절을_나누고_조문_머리를_label과_heading으로_가른다():
    text = "# 제목\n\n## 제1조(목적)\n본문 1\n\n## 열람 제한\n본문 2\n\n## 제2조의3(대결)\n본문 3\n## 빈 절\n"
    assert split_sections(text) == [
        {"label": "제1조", "heading": "목적", "text": "본문 1"},
        {"label": None, "heading": "열람 제한", "text": "본문 2"},
        {"label": "제2조의3", "heading": "대결", "text": "본문 3"},
    ]


# ---------------------------------------------------------------- 결재선(#187)


def test_결재선은_양식의_금액_구간마다_한_줄로_쓴다(pack):
    assert render_text("{{ approval_line:purchase }}", pack) == (
        "- 합계 5,000,000원 이하: 팀장\n- 합계 5,000,000원 초과: 팀장 → 본부장"
    )


def test_결재선_기준_금액은_팩을_따른다(pack):
    import copy
    from unittest.mock import patch

    forms = copy.deepcopy(pack.forms)
    rule = next(f for f in forms if f["id"] == "purchase")["approval_line"]
    rule[0]["when"] = {"amount_lte": 3000000}
    rule[1]["when"] = {"amount_gt": 3000000}
    with patch.object(type(pack), "forms", new=property(lambda self: forms)):
        assert "3,000,000원 이하: 팀장" in render_text("{{ approval_line:purchase }}", pack)


def test_글로_옮길_수_없는_결재선_조건이나_없는_양식은_실패한다(pack):
    from unittest.mock import patch

    forms = [{"id": "x", "fields": {"properties": {}}, "approval_line": [{"when": {"weekday": 1}, "steps": ["staff"]}]}]
    with patch.object(type(pack), "forms", new=property(lambda self: forms)):
        with pytest.raises(TemplateError, match="weekday"):
            render_text("{{ approval_line:x }}", pack)
    with pytest.raises(TemplateError):
        render_text("{{ approval_line:no-such-form }}", pack)


def test_구매_규정_템플릿을_채운다(pack):
    from rag.generate import render_document

    sections = {s["label"]: s for s in render_document("gen-purchase-rule", pack)}
    assert sections["제3조"]["heading"] == "결재선"
    assert "- 합계 5,000,000원 초과: 팀장 → 본부장" in sections["제3조"]["text"]
    assert "{{" not in "".join(s["text"] for s in sections.values())
