"""확인 셋 묶음 해시 확인(contracts/eval/confirm-sets.md, eval/protocol.md 7절).

묶음 폴더의 manifest(`manifest.json` 또는 `manifest.yaml`)에 `files`가 있습니다. 목록(`[{path, sha256}]`)과
객체(`{경로: sha256}`) 둘 다 읽습니다. 묶음 해시는 `files`를 경로 순으로 `<sha256>  <경로>` 줄로 이어 붙인
문자열의 SHA-256입니다. 끝 줄바꿈이 있는 계산과 없는 계산을 둘 다 하고, 계약 표와 맞는 쪽을 씁니다.
각 파일의 실제 SHA-256도 다시 계산해 manifest와 다르면 멈춥니다.

`run --bundle`은 실제로 읽는 시나리오 파일이 모두 manifest `files`에 있는지(`unlisted`), rag가 읽는 주입 문서
파일의 해시가 manifest 파일 중 하나와 같은지(`manifest_sha256s`)도 봅니다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness.paths import CONTRACTS

TABLE = CONTRACTS / "eval" / "confirm-sets.md"
MANIFESTS = ("manifest.json", "manifest.yaml", "manifest.yml")


class BundleError(ValueError):
    pass


@dataclass
class BundleCheck:
    name: str | None
    expected: str | None
    actual: str
    # 표와 맞은 계산(끝 줄바꿈 "있음"·"없음"), 맞지 않으면 None
    newline: str | None
    files: int
    mismatched_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.newline is not None and not self.mismatched_files


def recorded_hashes(table: Path = TABLE) -> dict[str, str]:
    """계약 표의 묶음 이름 → bundleSha256."""
    out = {}
    for line in table.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([\w.-]+)\s*\|.*`([0-9a-f]{64})`", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def load_manifest(bundle: Path) -> dict:
    for name in MANIFESTS:
        p = bundle / name
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            return json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
    raise BundleError(f"manifest가 없습니다: {bundle} ({', '.join(MANIFESTS)})")


def manifest_files(manifest: dict) -> dict[str, str]:
    files = manifest.get("files")
    if isinstance(files, dict):
        return {str(k): str(v) for k, v in files.items()}
    if isinstance(files, list):
        return {str(f["path"]): str(f["sha256"]) for f in files}
    raise BundleError("manifest의 files가 목록도 객체도 아닙니다")


def bundle_hashes(files: dict[str, str]) -> dict[str, str]:
    body = "\n".join(f"{sha}  {path}" for path, sha in sorted(files.items()))
    return {"없음": hashlib.sha256(body.encode()).hexdigest(),
            "있음": hashlib.sha256((body + "\n").encode()).hexdigest()}


def check(bundle: Path, name: str | None = None, table: Path = TABLE) -> BundleCheck:
    manifest = load_manifest(bundle)
    name = name or manifest.get("name") or manifest.get("bundle")
    files = manifest_files(manifest)
    expected = recorded_hashes(table).get(name) if name else None
    hashes = bundle_hashes(files)
    newline = next((k for k, v in hashes.items() if v == expected), None)
    actual = hashes[newline] if newline else hashes["없음"]
    bad = []
    for path, sha in files.items():
        p = (bundle / path).resolve()
        if bundle.resolve() not in p.parents or not p.is_file() or \
                hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            bad.append(path)
    return BundleCheck(name=name, expected=expected, actual=actual, newline=newline, files=len(files),
                       mismatched_files=sorted(bad))


def unlisted(bundle: Path, paths: Iterable[Path]) -> list[str]:
    """manifest `files`에 없는 파일(묶음 밖 파일 포함)의 경로입니다."""
    root = bundle.resolve()
    listed = {(root / p).resolve() for p in manifest_files(load_manifest(bundle))}
    return sorted(str(p) for p in paths if p.resolve() not in listed)


def manifest_sha256s(bundle: Path) -> set[str]:
    return set(manifest_files(load_manifest(bundle)).values())


def describe(c: BundleCheck) -> str:
    if c.ok:
        return f"{c.name} `{c.actual}` = 계약 표(파일 {c.files}개, 끝 줄바꿈 {c.newline})"
    parts = [f"{c.name or '이름 없음'} `{c.actual}`"]
    if c.expected is None:
        parts.append("계약 표에 이 묶음이 없습니다")
    elif c.newline is None:
        parts.append(f"계약 표 `{c.expected}`와 다릅니다")
    if c.mismatched_files:
        parts.append(f"manifest와 내용이 다른 파일 {len(c.mismatched_files)}개")
    return ", ".join(parts)
