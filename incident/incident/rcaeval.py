"""외부 비교용 RCAEval 일부(RE3-SS: Sock Shop, 로그 포함, 30건)를 내려받습니다. 데이터는 커밋하지 않습니다.

    cd incident && uv run python -m incident.rcaeval            # data/external/RE3-SS/ 에 풀기
    cd incident && uv run python -m incident.rcaeval --list     # 받을 파일과 출처만 보기

출처: Pham et al., "RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data"
(https://github.com/phamquiluan/RCAEval). 데이터는 Zenodo 레코드 14590730(CC BY 4.0), 코드 저장소 README는 MIT입니다.
경우 폴더 이름이 정답 원인입니다({서비스}_{장애}_{번호}), inject_time.txt가 주입 시각(유닉스 초)입니다.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

EXTERNAL = Path(__file__).resolve().parents[1] / "data" / "external"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    md5: str
    size_mb: float
    license: str
    citation: str


RE3_SS = Source(
    name="RE3-SS",
    url="https://zenodo.org/records/14590730/files/RE3-SS.zip?download=1",
    md5="467964eddb2a4fef4d6486c4679e749b",
    size_mb=101.5,
    license="CC BY 4.0 (Zenodo 레코드 14590730). 코드 저장소 README는 MIT",
    citation="Pham et al., RCAEval (WWW 2025 Companion), https://github.com/phamquiluan/RCAEval",
)


def md5sum(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(src: Source, dest: Path = EXTERNAL) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / f"{src.name}.zip"
    if not zip_path.exists() or md5sum(zip_path) != src.md5:
        tmp = zip_path.with_suffix(".part")
        with httpx.stream("GET", src.url, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        if md5sum(tmp) != src.md5:
            tmp.unlink()
            raise ValueError(f"{src.name}: md5가 Zenodo에 적힌 값과 다릅니다")
        tmp.replace(zip_path)
    out = dest / src.name
    if out.exists():
        shutil.rmtree(out)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = (dest / member).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise ValueError(f"압축 안 경로가 바깥을 가리킵니다: {member}")
        z.extractall(dest)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list:
        print(f"{RE3_SS.name}: {RE3_SS.url} ({RE3_SS.size_mb} MB, md5 {RE3_SS.md5})\n라이선스: {RE3_SS.license}\n"
              f"출처: {RE3_SS.citation}")
        return 0
    print(f"풀었습니다: {download(RE3_SS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
