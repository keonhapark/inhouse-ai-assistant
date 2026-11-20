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
