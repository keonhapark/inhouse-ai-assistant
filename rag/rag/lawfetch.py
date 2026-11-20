"""법제처 국가법령정보센터에서 공개 규정 고정본을 만듭니다.

1단계는 Open API 인증값(OC) 없이 국가법령정보센터 웹 화면이 쓰는 본문 주소에서 받습니다.
받은 본문을 조문(법령) 또는 절(행정규칙 첨부 PDF) 단위로 나눠 `corpus/law/<문서 ID>.json`에 둡니다.
`sources.yaml`에 `editions`(옛 판)가 있으면 그 판도 받아 `corpus/law/<문서 ID>@<시행일>.json`에 둡니다.
검색과 인용 대조는 이 고정본만 봅니다. 시행일·조회일·원문 SHA-256을 함께 적어 언제 받은 판인지 남깁니다.

실행(rag/에서): uv run --group fetch python -m rag.lawfetch [문서 ID ...]
대상 목록: corpus/law/sources.yaml
"""

from __future__ import annotations

import hashlib
import html as htmlmod
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from rag.corpus import LAW_DIR

BASE = "https://www.law.go.kr/LSW"
USER_AGENT = "Mozilla/5.0 (compatible; rag-lawfetch/0.1)"

# ---------------------------------------------------------------- 법령(HTML)

_LAWCON_OPEN = '<div class="lawcon">'
_DIV = re.compile(r"<div\b[^>]*>|</div>")
_LABEL = re.compile(r"<label[^>]*>\s*(.*?)\s*</label>", re.S)
_ARTICLE = re.compile(r"^(제\d+조(?:의\d+)?)(?:\((.*)\))?$")
_ANNOTATION = re.compile(r'<span class="sfon">.*?</span>', re.S)
_TAG = re.compile(r"<[^>]+>")
_IMG_ALT = re.compile(r'<img[^>]*?alt="([^"]*)"[^>]*>', re.S)
_HEADER = re.compile(r"<h2>\s*(.*?)\s*</h2>\s*<div class=\"ct_sub\">\s*<span>\s*(\[시행[^<]*)</span>", re.S)
_ENFORCE = re.compile(r"\[시행\s*([\d.\s]+)\]\s*\[([^\]]+)\]")


def _clean(fragment: str) -> str:
    """태그를 지우고 공백을 하나로 줄입니다. 태그 자리에 공백을 넣으면 "제55조 에"처럼 끊기므로 그냥 지웁니다."""
    text = htmlmod.unescape(_TAG.sub("", fragment))
    return re.sub(r"\s+", " ", text).strip()


def _lawcon_blocks(page: str) -> list[str]:
    """조문 상자(`div.lawcon`)의 본문을 돌려줍니다. 안쪽 div(위임행정규칙 버튼·목록)는 통째로 뺍니다."""
    blocks = []
    start = page.find(_LAWCON_OPEN)
    while start != -1:
        pos, depth, kept, cut = start + len(_LAWCON_OPEN), 1, [], start + len(_LAWCON_OPEN)
        for m in _DIV.finditer(page, pos):
            if m.group(0) == "</div>":
                depth -= 1
                if depth == 0:
                    kept.append(page[cut : m.start()])
                    pos = m.end()
                    break
                if depth == 1:
                    cut = m.end()
            else:
                if depth == 1:
                    kept.append(page[cut : m.start()])
                depth += 1
        else:
            raise ValueError("조문 상자가 닫히지 않았습니다")
        blocks.append("".join(kept))
        start = page.find(_LAWCON_OPEN, pos)
    return blocks


def _date(dotted: str) -> str:
    y, m, d = (int(x) for x in re.findall(r"\d+", dotted)[:3])
    return f"{y:04d}-{m:02d}-{d:02d}"


def parse_law_html(page: str) -> dict[str, Any]:
    """lsInfoR 본문 HTML에서 제목·시행일·공포 정보와 조문 목록을 뽑습니다. 삭제된 조문은 뺍니다."""
    head = _HEADER.search(page)
    if not head:
        raise ValueError("법령 제목과 시행 정보를 찾지 못했습니다")
    title = _clean(head.group(1))
    enforce = _ENFORCE.search(_clean(head.group(2)))
    if not enforce:
        raise ValueError("시행 정보 형식이 다릅니다")
    sections = []
    for block in _lawcon_blocks(page):
        m = _LABEL.search(block)
        if not m:
            continue
        am = _ARTICLE.match(_clean(m.group(1)))
        if not am:
            continue
        body = _ANNOTATION.sub("", block[m.end() :])
        # 조문 속 표는 그림이고 대체 글자에 행이 줄마다 들어 있습니다. 행을 줄로 남깁니다.
        body = _IMG_ALT.sub(lambda im: "</p>" + "</p>".join(im.group(1).splitlines()) + "</p>", body)
        lines = [_clean(p) for p in re.split(r"</p>", body)]
        lines = [x for x in lines if x]
        if not lines or lines == ["삭제"]:
            continue
        sections.append({"label": am.group(1), "heading": am.group(2), "text": "\n".join(lines)})
    if not sections:
        raise ValueError("조문을 찾지 못했습니다")
    return {
        "title": title,
        "effectiveDate": _date(enforce.group(1)),
        "promulgation": enforce.group(2).strip(),
        "sections": sections,
    }


# ---------------------------------------------------------------- 행정규칙(첨부 PDF)

_TOC = re.compile(r"제\s*(\d+)\s*장\s+(.+?)[·…\.\s]{3,}\s*(\d+)\s*$")
_TOP = re.compile(r"^(\d+)\.\s+(.+)$")
_SUB = re.compile(r"^\s?([가-하])\.\s+(.+)$")
_LETTERS = "가나다라마바사아자차카타파하"
_MAX_HEAD = 30  # 이보다 긴 "가." 줄은 머리가 아니라 문장으로 봅니다.


def _squash(heading: str) -> str:
    """"근 거", "정  의"처럼 한 글자씩 띄운 머리를 붙입니다."""
    parts = heading.split()
    if len(parts) > 1 and all(len(p) == 1 for p in parts):
        return "".join(parts)
    return re.sub(r"\s+", " ", heading).strip()


def chapter_pages(pages: list[str], chapter: int) -> tuple[str, list[str]]:
    """목차에서 장의 시작·끝 쪽 번호를 찾고, 쪽 첫 줄의 쪽 번호로 PDF 쪽을 고릅니다."""
    toc: dict[int, tuple[str, int]] = {}
    for page in pages[:6]:
        for line in page.splitlines():
            if m := _TOC.search(line):
                toc.setdefault(int(m.group(1)), (_squash(m.group(2)), int(m.group(3))))
    if chapter not in toc or chapter + 1 not in toc:
        raise ValueError(f"목차에서 제{chapter}장을 찾지 못했습니다")
    name, start = toc[chapter]
    end = toc[chapter + 1][1]
    # 쪽 번호가 범위 안인 첫 쪽과 마지막 쪽 사이를 모두 고릅니다. 쪽 번호를 못 읽은 쪽이 중간에서 빠지지 않게 합니다.
    inside = []
    for i, page in enumerate(pages):
        first = page.strip().split("\n", 1)[0].strip()
        if first.isdigit() and start <= int(first) < end:
            inside.append(i)
    if not inside:
        raise ValueError(f"제{chapter}장 쪽({start}~{end - 1})을 찾지 못했습니다")
    return name, pages[inside[0] : inside[-1] + 1]


def parse_admrul_chapter(pages: list[str], chapter: int, rule_title: str) -> tuple[str, list[dict[str, Any]]]:
    """장 하나를 "1."과 "가." 두 단계의 절로 나눕니다.

    번호는 앞 번호의 다음 번호일 때만 머리로 봅니다. 본문 속 목록("1. 「병역법」…")이나
    인용한 다른 규정의 번호가 머리로 잡히지 않게 하려는 것입니다.
    """
    name, picked = chapter_pages(pages, chapter)
    noise = {rule_title.replace("·", "․"), rule_title, f"제{chapter}장 / {name}", "제  장", "제 장"}
    lines: list[str] = []
    for page in picked:
        for line in page.splitlines():
            s = line.strip()
            if not s or s.isdigit() or s in noise or re.fullmatch(rf"제\s*{chapter}\s*장\s*/.*", s):
                continue
            if _squash(s) == name and len(lines) < 3:
                continue
            lines.append(line.rstrip())

    sections: list[dict[str, Any]] = []
    top_no, top_head, sub_idx = 0, "", -1
    label: str | None = None
    heading: str | None = None
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(x.strip() for x in buf).strip()
        if text:
            sections.append({"label": label, "heading": heading, "text": text})
        elif label and heading and " > " in heading:
            # "가. 국가공무원 복무규정 제14조 내지 제24조의3"처럼 머리 자체가 내용인 절
            sections.append({"label": label, "heading": heading.split(" > ", 1)[0], "text": heading.split(" > ", 1)[1]})

    for line in lines:
        if (m := _TOP.match(line)) and int(m.group(1)) == top_no + 1:
            flush()
            top_no, top_head, sub_idx = int(m.group(1)), _squash(m.group(2)), -1
            label, heading, buf = f"{top_no}.", top_head, []
            continue
        if top_no and (m := _SUB.match(line)) and sub_idx + 1 < len(_LETTERS) and m.group(1) == _LETTERS[sub_idx + 1]:
            flush()
            sub_idx += 1
            label, sub = f"{top_no}. {m.group(1)}.", _squash(m.group(2))
            if len(sub) > _MAX_HEAD:
                heading, buf = top_head, [line]
            else:
                heading, buf = f"{top_head} > {sub}", []
            continue
        buf.append(line)
    flush()
    return name, sections


# ---------------------------------------------------------------- 받기

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (고정 주소)
        return resp.read()


def _q(text: str) -> str:
    return urllib.parse.quote(text)


def _law_page(doc_id: str, spec: dict[str, Any], lsi_seq: str, ef_yd: str | None) -> dict[str, Any]:
    query = f"lsiSeq={lsi_seq}&chrClsCd=010202&urlMode=lsInfoP" + (f"&efYd={ef_yd}" if ef_yd else "")
    raw = _get(f"{BASE}/lsInfoR.do?{query}")
    parsed = parse_law_html(raw.decode("utf-8"))
    if parsed["title"] != spec["name"]:
        raise ValueError(f"{doc_id}: 받은 법령 이름 {parsed['title']}이 {spec['name']}과 다릅니다")
    return {
        "title": parsed["title"],
        "url": f"{BASE}/lsInfoP.do?lsiSeq={lsi_seq}" + (f"&efYd={ef_yd}" if ef_yd else ""),
        "effectiveDate": parsed["effectiveDate"],
        "promulgation": parsed["promulgation"],
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "extent": "본칙 전체(부칙·별표 제외)",
        "sections": parsed["sections"],
    }


def fetch_law(doc_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """현행 판."""
    link = _get(f"{BASE}/lsLinkProc.do?lsNm={_q(spec['name'])}&chrClsCd=010202&mode=20").decode("utf-8")
    seq = re.search(r"lsiSeq\s*:\s*'(\d+)'", link)
    ef = re.search(r"efYd\s*[:=]\s*'(\d{8})'", link)
    if not seq:
        raise ValueError(f"{doc_id}: 법령 일련번호를 찾지 못했습니다")
    got = _law_page(doc_id, spec, seq.group(1), ef.group(1) if ef else None)
    got["url"] = f"{BASE}/lsInfoP.do?lsiSeq={seq.group(1)}"
    return got


def fetch_law_edition(doc_id: str, spec: dict[str, Any], edition: dict[str, Any]) -> dict[str, Any]:
    """옛 판. `sources.yaml`의 `editions` 항목(연혁 화면의 lsiSeq와 시행일 efYd)으로 받습니다."""
    got = _law_page(doc_id, spec, str(edition["lsiSeq"]), str(edition["efYd"]))
    ef = str(edition["efYd"])
    want = f"{ef[:4]}-{ef[4:6]}-{ef[6:]}"
    if got["effectiveDate"] != want:
        raise ValueError(f"{doc_id}: 받은 판의 시행일 {got['effectiveDate']}이 {want}과 다릅니다")
    return got


def fetch_admrul(doc_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    from pypdf import PdfReader  # 받을 때만 씁니다(의존 그룹 fetch)

    link = _get(f"{BASE}/admRulLinkProc.do?admRulNm={_q(spec['name'])}").decode("utf-8")
    seq = re.search(r'admRulSeq\s*:\s*"(\d+)"', link)
    if not seq:
        raise ValueError(f"{doc_id}: 행정규칙 일련번호를 찾지 못했습니다")
    info = _get(f"{BASE}/admRulLsInfoR.do?admRulSeq={seq.group(1)}").decode("utf-8")
    text = _clean(info)
    title_ok = spec["name"] in text
    enforce = _ENFORCE.search(text)
    files = re.findall(r"key=(\d+)&amp;contextPath=/viewer/DATA/ADMRUL", info)
    if not (title_ok and enforce and files):
        raise ValueError(f"{doc_id}: 행정규칙 정보나 첨부 파일을 찾지 못했습니다")
    raw = _get(f"{BASE}/flDownload.do?flSeq={files[0]}")
    pages = [p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages]
    name, sections = parse_admrul_chapter(pages, spec["chapter"], spec["name"])
    return {
        "title": spec["name"],
        "url": f"{BASE}/admRulLsInfoP.do?admRulSeq={seq.group(1)}",
        "effectiveDate": _date(enforce.group(1)),
        "promulgation": enforce.group(2).strip(),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "extent": f"첨부 PDF 제{spec['chapter']}장 {name}(글자는 PDF에서 뽑음, 표 모양은 남지 않음)",
        "sections": sections,
    }


def build_copy(
    doc_id: str, spec: dict[str, Any], now: datetime | None = None, edition: dict[str, Any] | None = None
) -> dict[str, Any]:
    if edition is not None:
        got = fetch_law_edition(doc_id, spec, edition)
    else:
        got = fetch_law(doc_id, spec) if spec["kind"] == "law" else fetch_admrul(doc_id, spec)
    sections = got.pop("sections")
    title = got.pop("title")
    got["retrievedAt"] = (now or datetime.now(timezone.utc)).astimezone().isoformat(timespec="seconds")
    return {"id": doc_id, "title": title, "source": got, "sections": sections}


def _write(copy: dict[str, Any], out: Path) -> None:
    out.write_text(json.dumps(copy, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    src = copy["source"]
    print(f"{copy['id']}: {copy['title']} 시행 {src['effectiveDate']}, 절 {len(copy['sections'])}개 → {out.name}")


def main(argv: list[str]) -> int:
    specs = yaml.safe_load((LAW_DIR / "sources.yaml").read_text(encoding="utf-8"))
    targets = argv or list(specs)
    for doc_id in targets:
        spec = specs[doc_id]
        _write(build_copy(doc_id, spec), LAW_DIR / f"{doc_id}.json")
        for edition in spec.get("editions", []):
            copy = build_copy(doc_id, spec, edition=edition)
            _write(copy, LAW_DIR / f"{doc_id}@{copy['source']['effectiveDate']}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
