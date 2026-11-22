"""도구 호출 QLoRA 학습(#545, #111). GPU 사용권(scripts/gpu-lease.sh)을 받은 동안에만 돌립니다.

학습 환경은 저장소 밖 가상환경(`lora/install_qlora.sh`)이고, 결과(어댑터·체크포인트·기록)도 저장소 밖에 씁니다.
기본 모델은 Hugging Face `Qwen/Qwen3.5-9B`(Apache-2.0)입니다. 4비트(NF4, 이중 양자화)로 올리고 언어 모델의
attention·MLP 선형층에만 LoRA를 붙입니다(비전 쪽은 건드리지 않음). 정답(assistant) 토큰만 손실에 넣습니다(`qlora_data.py`).

chat template은 생각 끔(`enable_thinking=False`, 빈 `<think></think>` 뒤에 정답)으로 만듭니다. 학습 데이터에 생각 내용이 없어
생각 켬 형식으로 만들면 빈 생각을 가르치게 되고, 토큰 경계도 생성 프롬프트(`<think>\n`)와 어긋납니다. 업무 경로는 생각 켬이
기본이라(결정 0008) 평가는 생각 끔·켬 둘 다 합니다(`compare_runs.py`).

    # 토큰 길이·버리는 예시만 보기(GPU 없음, 토크나이저만 받음)
    ~/.cache/iaa-qlora-venv/bin/python lora/train_qlora.py --data <생성 폴더> --out <저장소 밖> --dry-run
    # 학습
    ~/.cache/iaa-qlora-venv/bin/python lora/train_qlora.py --data <생성 폴더> --out <저장소 밖> [--epochs 2] [--seed 7]

출력(`--out`): `adapter/`(PEFT 어댑터), `checkpoints/`, `run.json`(설정, 기본 모델 리비전, 데이터 manifest, 판 번호,
저장소 커밋, 손실 기록, GPU, 걸린 시간).
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from qlora_data import collate, encode_all, read_rows  # noqa: E402

# 언어 모델의 attention(q·k·v·o)과 MLP(gate·up·down) 선형층. 비전 인코더는 이름에 visual이 들어가 빠집니다.
DEFAULT_TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"


def progress_line(step: int, max_steps: int, loss: float | None, elapsed: float) -> str:
    """'진행 120/2488 손실 0.4123 경과 12분 남은 약 236분'. 남은 시간은 지금까지의 평균 단계 시간으로 어림합니다."""
    rest = (max_steps - step) * elapsed / step / 60 if step else None
    loss_text = f"{loss:.4f}" if loss is not None else "-"
    rest_text = f"{rest:.0f}분" if rest is not None else "-"
    return f"진행 {step}/{max_steps} 손실 {loss_text} 경과 {elapsed / 60:.0f}분 남은 약 {rest_text}"


def outside_repo(path: Path) -> Path:
    p = path.expanduser().resolve()
    if p == REPO or REPO in p.parents:
        raise SystemExit("학습 결과는 저장소 밖에 씁니다(--out)")
    return p


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="make_toolcall_data.py 출력 폴더(train.jsonl·valid.jsonl·manifest.json)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-model", default="Qwen/Qwen3.5-9B")
    ap.add_argument("--revision", default=None, help="기본 모델 리비전(빼면 지금 main을 받아 run.json에 sha를 남김)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--lora-dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", default=DEFAULT_TARGETS)
    ap.add_argument("--max-len", type=int, default=2048, help="기본 데이터는 최대 1,834토큰(Qwen3.5 토크나이저)")
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--progress-minutes", type=float, default=3,
                    help="이 간격(분)마다 단계·손실·남은 시간을 한 줄로 출력(노트북 셀 출력용)")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    out = outside_repo(Path(args.out))
    data = Path(args.data)
    from huggingface_hub import HfApi
    from transformers import AutoTokenizer

    revision = args.revision or HfApi().model_info(args.base_model).sha
    tok = AutoTokenizer.from_pretrained(args.base_model, revision=revision)
    kwargs = {"enable_thinking": False}
    train, s_train = encode_all(read_rows(data / "train.jsonl"), tok, args.max_len, kwargs)
    valid, s_valid = encode_all(read_rows(data / "valid.jsonl"), tok, args.max_len, kwargs)
    lengths = sorted(len(e.input_ids) for e in train)
    summary = {"train": vars(s_train) | {"target_tokens": sum(s_train.target_tokens)},
               "valid": vars(s_valid) | {"target_tokens": sum(s_valid.target_tokens)},
               "lengthP50": lengths[len(lengths) // 2] if lengths else None, "lengthMax": lengths[-1] if lengths else None}
    print(json.dumps(summary, ensure_ascii=False))
    if not train:
        raise SystemExit("쓸 수 있는 학습 예시가 없습니다(too_long·prefix_mismatch 확인)")
    if args.dry_run:
        return 0

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForImageTextToText, BitsAndBytesConfig, Trainer, TrainingArguments,
                              set_seed)

    set_seed(args.seed)
    # RTX 40은 bf16, 코랩 T4는 bf16을 지원하지 않아 fp16으로 계산합니다
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    compute = torch.bfloat16 if bf16 else torch.float16
    model = AutoModelForImageTextToText.from_pretrained(
        args.base_model, revision=revision, device_map="auto", dtype=compute,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
                                             target_modules=args.target_modules, task_type="CAUSAL_LM"))
    trainable, total = model.get_nb_trainable_parameters()
    print(f"학습 파라미터 {trainable:,} / {total:,}")
    if trainable == 0:
        raise SystemExit("LoRA를 붙인 층이 없습니다(--target-modules 확인)")

    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    def to_tensors(batch: list[Any]) -> dict[str, Any]:
        return {k: torch.tensor(v) for k, v in collate(batch, pad_id).items()}

    trainer = Trainer(
        model=model, train_dataset=train, eval_dataset=valid, data_collator=to_tensors,
        args=TrainingArguments(output_dir=str(out / "checkpoints"), per_device_train_batch_size=args.batch,
                               per_device_eval_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
                               num_train_epochs=args.epochs, learning_rate=args.lr, lr_scheduler_type="cosine",
                               warmup_ratio=0.03, bf16=bf16, fp16=not bf16, logging_steps=10, eval_strategy="epoch",
                               save_strategy="epoch", save_total_limit=2, seed=args.seed, optim="paged_adamw_8bit",
                               gradient_checkpointing=True, remove_unused_columns=False, report_to=[]))
    from transformers import TrainerCallback

    class Progress(TrainerCallback):
        """몇 분마다 한 줄씩 출력합니다(tqdm 막대가 노트북 셀 출력에 남지 않는 경우를 위해)."""

        def __init__(self) -> None:
            self.last = 0.0
            self.loss: float | None = None

        def on_log(self, args_, state, control, logs=None, **kw):  # noqa: ANN001
            if logs and "loss" in logs:
                self.loss = float(logs["loss"])

        def on_step_end(self, args_, state, control, **kw):  # noqa: ANN001
            now = time.time()
            if now - self.last >= args.progress_minutes * 60 or state.global_step == state.max_steps:
                self.last = now
                print(progress_line(state.global_step, state.max_steps, self.loss, now - started), flush=True)

    trainer.add_callback(Progress())
    started = time.time()
    trainer.train()
    model.save_pretrained(out / "adapter")
    tok.save_pretrained(out / "adapter")

    import peft
    import transformers
    manifest = json.loads((data / "manifest.json").read_text("utf-8")) if (data / "manifest.json").exists() else None
    run = {"finishedAt": datetime.now(timezone.utc).isoformat(), "seconds": round(time.time() - started),
           "baseModel": args.base_model, "revision": revision, "args": {k: v for k, v in vars(args).items()
                                                                       if k not in ("data", "out")},
           "data": {"manifest": manifest, "encode": summary}, "repoCommit": git_commit(),
           "versions": {"python": platform.python_version(), "torch": torch.__version__,
                        "transformers": transformers.__version__, "peft": peft.__version__},
           "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
           "computeDtype": str(compute).removeprefix("torch."),
           "trainablePercent": round(100 * trainable / total, 3), "log": trainer.state.log_history}
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"어댑터 {out / 'adapter'}, 기록 {out / 'run.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
