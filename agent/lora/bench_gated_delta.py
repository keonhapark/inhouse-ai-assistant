"""Qwen3.5 Gated DeltaNet 층 한 개의 순전파+역전파 시간을 구현별로 잽니다(#618). 모델은 받지 않습니다.

- torch: transformers의 참조 구현(`torch_chunk_gated_delta_rule`, 청크 64 파이썬 반복문). flash-linear-attention이 없을 때
  transformers가 쓰는 것
- fla: flash-linear-attention의 `chunk_gated_delta_rule`(Triton). T4(sm75)에서 도는지도 여기서 봅니다

크기는 Qwen3.5-9B 선형 어텐션 층(값 머리 32개, 머리 크기 128, q·k는 값 머리 수로 늘린 뒤)이고 길이는 학습 상한 2048입니다.
두 구현의 순전파 출력 차이(최대 절대 오차)도 남깁니다.

    python lora/bench_gated_delta.py --out gdn-bench.json [--seq 2048] [--repeat 3]
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def _version(pkg: str) -> str | None:
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None


def implementations() -> dict[str, Any]:
    """{이름: 함수 또는 들여오기 오류 글}."""
    out: dict[str, Any] = {}
    from transformers.models.qwen3_5 import modeling_qwen3_5 as m

    fn = m.torch_chunk_gated_delta_rule
    out["torch"] = getattr(fn, "__wrapped__", fn)  # fla가 있으면 장식자가 fla로 바꾸므로 원래 함수를 꺼냅니다
    try:
        from fla.ops.gated_delta_rule import chunk_gated_delta_rule
        out["fla"] = chunk_gated_delta_rule
    except Exception as e:  # noqa: BLE001 - 들여오기 실패 이유를 기록에 남깁니다
        out["fla"] = f"{type(e).__name__}: {e}"
    return out


def inputs(torch: Any, seq: int, heads: int, dim: int, dtype: Any, device: str, seed: int = 0) -> list[Any]:
    g = torch.Generator(device="cpu").manual_seed(seed)

    def rnd(*shape: int) -> Any:
        return torch.randn(*shape, generator=g)

    q, k, v = rnd(1, seq, heads, dim), rnd(1, seq, heads, dim), rnd(1, seq, heads, dim)
    gate = torch.nn.functional.logsigmoid(rnd(1, seq, heads))  # 0 이하(감쇠의 로그)
    beta = torch.sigmoid(rnd(1, seq, heads))
    return [x.to(device=device, dtype=dtype).requires_grad_(True) for x in (q, k, v, gate, beta)]


def run_once(torch: Any, fn: Any, xs: list[Any]) -> Any:
    out, _ = fn(xs[0], xs[1], xs[2], g=xs[3], beta=xs[4], initial_state=None, output_final_state=False,
                use_qk_l2norm_in_kernel=True)
    out.float().square().mean().backward()
    return out.detach()


def bench(torch: Any, fn: Any, xs: list[Any], repeat: int, device: str) -> dict[str, Any]:
    sync = torch.cuda.synchronize if device.startswith("cuda") else (lambda: None)
    out = run_once(torch, fn, xs)  # 처음 한 번(Triton 컴파일 포함)은 재지 않음
    sync()
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    times = []
    for _ in range(repeat):
        for x in xs:
            x.grad = None
        t = time.perf_counter()
        run_once(torch, fn, xs)
        sync()
        times.append((time.perf_counter() - t) * 1000)
    peak = torch.cuda.max_memory_allocated() / 2**30 if device.startswith("cuda") else None
    return {"ok": True, "fwdBwdMs": [round(x, 1) for x in times], "fwdBwdMsMin": round(min(times), 1),
            "peakMemoryGB": round(peak, 2) if peak is not None else None, "_out": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seq", type=int, default=2048)
    ap.add_argument("--heads", type=int, default=32)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--device", default="cuda")
    args = ap.parse_args(argv)

    import torch

    cuda = args.device.startswith("cuda")
    dtype = torch.bfloat16 if cuda and torch.cuda.is_bf16_supported() else (torch.float16 if cuda else torch.float32)
    report: dict[str, Any] = {
        "seq": args.seq, "heads": args.heads, "dim": args.dim, "dtype": str(dtype).removeprefix("torch."),
        "device": args.device, "gpu": torch.cuda.get_device_name(0) if cuda else None,
        "capability": list(torch.cuda.get_device_capability(0)) if cuda else None,
        "versions": {"python": platform.python_version(), "torch": torch.__version__, "triton": _version("triton"),
                     "transformers": _version("transformers"), "fla-core": _version("fla-core")},
        "results": {}}
    outs = {}
    for name, fn in implementations().items():
        if isinstance(fn, str):
            report["results"][name] = {"ok": False, "error": fn}
            continue
        try:
            r = bench(torch, fn, inputs(torch, args.seq, args.heads, args.dim, dtype, args.device), args.repeat,
                      args.device)
            outs[name] = r.pop("_out")
            report["results"][name] = r
        except Exception as e:  # noqa: BLE001 - T4에서 커널이 안 도는 경우를 기록합니다
            report["results"][name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:500]}"}
        if cuda:
            torch.cuda.empty_cache()
    if len(outs) == 2:
        report["maxAbsDiff"] = float((outs["torch"].float() - outs["fla"].float()).abs().max())
        a, b = report["results"]["torch"], report["results"]["fla"]
        report["speedup"] = round(a["fwdBwdMsMin"] / b["fwdBwdMsMin"], 1)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
