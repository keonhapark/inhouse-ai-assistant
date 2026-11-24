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
    # GPU 두 장에 모델을 한 벌씩(데이터 병렬). 누적을 절반으로 줄여 한 최적화 단계의 예시 수(8)를 맞춥니다
    torchrun --nproc_per_node 2 lora/train_qlora.py --data <생성 폴더> --out <저장소 밖> --grad-accum 4

속도(#618): 모델은 기본으로 GPU 한 장에 다 올립니다(`--placement one`, 데이터 병렬이면 프로세스마다 자기 GPU).
`--placement split`은 예전처럼 층을 여러 GPU에 나눠 올려 GPU가 차례로 돕니다. 손실은 정답 토큰을 맞히는 자리의 logits만
만들어 계산하고(값은 기본 손실과 같음), Qwen3.5의 Gated DeltaNet 층은 flash-linear-attention이 있으면 그 커널을 씁니다.

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
from qlora_data import answer_positions, collate, encode_all, read_rows  # noqa: E402

# 언어 모델의 attention(q·k·v·o)과 MLP(gate·up·down) 선형층. 비전 인코더는 이름에 visual이 들어가 빠집니다.
DEFAULT_TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"


def progress_line(step: int, max_steps: int, loss: float | None, elapsed: float, start_step: int = 0,
                  peak_gb: float | None = None) -> str:
    """'진행 120/2488 손실 0.4123 경과 12분 남은 약 237분 단계당 6.0초 GPU 최대 11.2GB'.
    남은 시간은 이번 실행에서 돈 단계(이어 돌리면 start_step부터)의 평균 단계 시간으로 어림합니다."""
    done = step - start_step
    per_step = elapsed / done if done > 0 else None
    loss_text = f"{loss:.4f}" if loss is not None else "-"
    rest_text = f"{(max_steps - step) * per_step / 60:.0f}분" if per_step is not None else "-"
    line = f"진행 {step}/{max_steps} 손실 {loss_text} 경과 {elapsed / 60:.0f}분 남은 약 {rest_text}"
    if per_step is not None:
        line += f" 단계당 {per_step:.1f}초"
    if peak_gb is not None:
        line += f" GPU 최대 {peak_gb:.1f}GB"
    return line


def placement_map(placement: str, env: dict[str, str]) -> dict[str, int] | str:
    """from_pretrained의 device_map. one: 이 프로세스의 GPU 한 장에 다(torchrun이면 LOCAL_RANK), split: 층을 나눠 올림."""
    if placement == "split":
        return "auto"
    return {"": int(env.get("LOCAL_RANK", "0"))}


def answer_loss(model: Any, inputs: dict[str, Any], num_items_in_batch: Any = None, scale: int = 1) -> tuple[Any, Any]:
    """정답 자리(`answer_positions`)의 logits만 만들어 교차 엔트로피 합을 냅니다. num_items_in_batch가 있으면 그 수로 나누고
    (누적 전체 정답 토큰 수) scale을 곱하며, 없으면 이 배치의 정답 토큰 평균입니다. (손실, 모델 출력)을 돌려줍니다."""
    import torch.nn.functional as F

    keep, labels = inputs["answer_positions"], inputs["labels"]
    out = model(input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], logits_to_keep=keep)
    targets = labels[:, 1:][keep[:, :-1]]
    loss = F.cross_entropy(out.logits.float(), targets, reduction="sum")
    if num_items_in_batch is None:
        return loss / max(targets.numel(), 1), out
    return loss / num_items_in_batch * scale, out


def gated_delta_backend() -> str:
    """Qwen3.5 Gated DeltaNet 층이 쓸 구현. transformers는 fla를 들여올 수 있으면 그 커널, 아니면 torch 대체 구현을 씁니다."""
    try:
        from fla.ops.gated_delta_rule import chunk_gated_delta_rule  # noqa: F401
    except Exception:  # noqa: BLE001 - 설치 안 됨·들여오기 실패 모두 torch 대체 구현으로 갑니다
        return "torch"
    return "fla"


def training_kwargs(args: argparse.Namespace, out: Path, bf16: bool) -> dict[str, Any]:
    """TrainingArguments 인자. transformers 5에는 warmup_ratio가 없고, warmup_steps에 [0, 1) 실수를 주면 비율입니다."""
    return {"output_dir": str(out / "checkpoints"), "per_device_train_batch_size": args.batch,
            "per_device_eval_batch_size": args.batch, "gradient_accumulation_steps": args.grad_accum,
            "num_train_epochs": args.epochs, "learning_rate": args.lr, "lr_scheduler_type": "cosine",
            "warmup_steps": 0.03, "bf16": bf16, "fp16": not bf16, "logging_steps": 10, "eval_strategy": "epoch",
            "save_strategy": "epoch", "save_total_limit": 2, "seed": args.seed, "optim": "paged_adamw_8bit",
            "gradient_checkpointing": True, "gradient_checkpointing_kwargs": {"use_reentrant": False},
            "remove_unused_columns": False, "ddp_find_unused_parameters": False, "report_to": []}


def check_training_setup(kw: dict[str, Any], train: list[Any], valid: list[Any]) -> list[str]:
    """dry-run에서 모델 없이 학습 설정을 미리 봅니다(#551 v2는 TrainingArguments 인자 이름에서 멈춤).

    1. 인자 이름이 이 transformers 판 TrainingArguments 필드에 있는지(torch 없이)
    2. torch가 있으면 TrainingArguments를 실제로 만들고, Trainer 생성 인자 이름도 확인
    문제를 글로 돌려줍니다(없으면 빈 목록).
    """
    import dataclasses
    import inspect

    from transformers import TrainingArguments

    names = {f.name for f in dataclasses.fields(TrainingArguments)}
    problems = [f"TrainingArguments에 없는 인자: {k}" for k in kw if k not in names]
    if problems:
        return problems
    try:
        import torch  # noqa: F401
    except ImportError:
        return []
    try:
        TrainingArguments(**kw)
        from transformers import Trainer
        params = inspect.signature(Trainer.__init__).parameters
        problems += [f"Trainer에 없는 인자: {k}" for k in ("model", "args", "train_dataset", "eval_dataset",
                                                         "data_collator") if k not in params]
    except Exception as e:  # noqa: BLE001 - 어떤 값이 틀렸는지 그대로 보여 줍니다
        problems.append(f"TrainingArguments 생성 실패: {type(e).__name__}: {e}")
    return problems


def last_checkpoint(out: Path) -> Path | None:
    """`checkpoints/checkpoint-<단계>` 중 단계가 가장 큰 것. trainer_state.json이 없는(저장 중 끊긴) 것은 건너뜁니다."""
    found = []
    for d in (out / "checkpoints").glob("checkpoint-*"):
        step = d.name.removeprefix("checkpoint-")
        if step.isdigit() and (d / "trainer_state.json").exists():
            found.append((int(step), d))
    return max(found)[1] if found else None


def due(now: float, last: float, minutes: float) -> bool:
    return minutes > 0 and now - last >= minutes * 60


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
    ap.add_argument("--save-minutes", type=float, default=25,
                    help="이 간격(분)마다 체크포인트 저장(epoch 끝 저장과 별도). 세션이 끊겨도 --resume으로 이어 갑니다")
    ap.add_argument("--resume", action="store_true",
                    help="--out/checkpoints의 마지막 체크포인트에서 이어 돌림(없으면 처음부터)")
    ap.add_argument("--progress-minutes", type=float, default=3,
                    help="이 간격(분)마다 단계·손실·남은 시간을 한 줄로 출력(노트북 셀 출력용)")
    ap.add_argument("--placement", choices=("one", "split"), default="one",
                    help="one: GPU 한 장에 모델을 다 올림(기본, 데이터 병렬도 이것). split: 층을 여러 GPU에 나눠 올림(차례로 돎)")
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
    try:
        import torch as _torch
        bf16_ok = _torch.cuda.is_available() and _torch.cuda.is_bf16_supported()
    except ImportError:
        bf16_ok = False
    problems = check_training_setup(training_kwargs(args, out, bf16_ok), train, valid)
    print("학습 설정 확인:", "문제 없음" if not problems else "; ".join(problems), flush=True)
    print(f"Gated DeltaNet 구현: {gated_delta_backend()}(fla가 아니면 대체 구현이라 느림, #618)", flush=True)
    if problems:
        raise SystemExit("학습 설정에 문제가 있습니다")
    if args.dry_run:
        return 0

    import os

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForImageTextToText, BitsAndBytesConfig, Trainer, TrainingArguments,
                              set_seed)

    set_seed(args.seed)
    # RTX 40은 bf16, 코랩 T4는 bf16을 지원하지 않아 fp16으로 계산합니다
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    compute = torch.bfloat16 if bf16 else torch.float16
    model = AutoModelForImageTextToText.from_pretrained(
        args.base_model, revision=revision, device_map=placement_map(args.placement, dict(os.environ)), dtype=compute,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute))
    # prepare_model_for_kbit_training은 양자화하지 않은 큰 텐서(임베딩·lm_head·비전 쪽)를 fp32로 올려 T4 한 장(15GB)에서
    # 메모리가 모자랐습니다(#551). 그 올림은 하지 않고 체크포인팅과 입력 기울기만 켭니다. LoRA 가중치는 PEFT가 fp32로 둡니다.
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    devices = sorted({str(d) for d in getattr(model, "hf_device_map", {}).values()})
    used = {i: round(torch.cuda.memory_allocated(i) / 2**30, 2) for i in range(torch.cuda.device_count())}
    backend = gated_delta_backend()
    print(f"모델 올림: 장치 {devices}, GPU 메모리(GB) {used}, Gated DeltaNet 구현 {backend}", flush=True)
    model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
                                             target_modules=args.target_modules, task_type="CAUSAL_LM"))
    trainable, total = model.get_nb_trainable_parameters()
    print(f"학습 파라미터 {trainable:,} / {total:,}")
    if trainable == 0:
        raise SystemExit("LoRA를 붙인 층이 없습니다(--target-modules 확인)")

    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    def to_tensors(batch: list[Any]) -> dict[str, Any]:
        cols = collate(batch, pad_id)
        return {k: torch.tensor(v) for k, v in cols.items()} | {"answer_positions": torch.tensor(
            answer_positions(cols["labels"]), dtype=torch.bool)}

    class AnswerLossTrainer(Trainer):
        """정답 토큰을 맞히는 자리의 logits만 만들어 손실을 냅니다(#618). 어휘 248,320 × 전체 길이(p50 1,296)의 logits와
        그 fp32 사본·기울기를 만들지 않습니다(정답은 예시당 약 50토큰). 손실 값은 기본 손실과 같습니다: 정답 토큰 교차
        엔트로피 합을 누적 전체 정답 토큰 수(num_items_in_batch)로 나눕니다. 그래서 누적 단계 수로 다시 나누지 않습니다."""
        loss_is_scaled_for_ga = True

        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):  # noqa: ANN001
            if num_items_in_batch is None and model.training:
                raise RuntimeError("학습 중 num_items_in_batch가 없어 누적 손실을 맞출 수 없습니다")
            # num_items_in_batch가 모든 프로세스의 합이고 DDP는 기울기를 프로세스 수로 평균하므로 프로세스 수를 곱해
            # 되돌립니다(Trainer 기본 compute_loss와 같은 처리)
            scale = self.accelerator.num_processes if self.args.average_tokens_across_devices else 1
            loss, out = answer_loss(model, inputs, num_items_in_batch, scale)
            return (loss, out) if return_outputs else loss

    trainer = AnswerLossTrainer(
        model=model, train_dataset=train, eval_dataset=valid, data_collator=to_tensors,
        args=TrainingArguments(**training_kwargs(args, out, bf16)))
    from transformers import TrainerCallback

    class Progress(TrainerCallback):
        """몇 분마다 한 줄씩 출력합니다(tqdm 막대가 노트북 셀 출력에 남지 않는 경우를 위해)."""

        def __init__(self) -> None:
            self.last = 0.0
            self.loss: float | None = None
            self.start_step = 0

        def on_train_begin(self, args_, state, control, **kw):  # noqa: ANN001
            self.start_step = state.global_step  # 이어 돌리면 체크포인트의 단계

        def on_log(self, args_, state, control, logs=None, **kw):  # noqa: ANN001
            if logs and "loss" in logs:
                self.loss = float(logs["loss"])

        def on_step_end(self, args_, state, control, **kw):  # noqa: ANN001
            now = time.time()
            if not state.is_world_process_zero:
                return
            if now - self.last >= args.progress_minutes * 60 or state.global_step == state.max_steps:
                self.last = now
                peak = torch.cuda.max_memory_allocated() / 2**30 if torch.cuda.is_available() else None
                print(progress_line(state.global_step, state.max_steps, self.loss, now - started, self.start_step,
                                    peak), flush=True)

    class TimedSave(TrainerCallback):
        """epoch 끝 저장과 별도로 --save-minutes마다 체크포인트를 남깁니다(save_total_limit로 오래된 것은 지움)."""

        def __init__(self) -> None:
            self.last = time.time()

        def on_step_end(self, args_, state, control, **kw):  # noqa: ANN001
            if due(time.time(), self.last, args.save_minutes):
                self.last = time.time()
                control.should_save = True
                if state.is_world_process_zero:
                    print(f"체크포인트 저장: 단계 {state.global_step}", flush=True)

    trainer.add_callback(Progress())
    trainer.add_callback(TimedSave())
    resume = last_checkpoint(out) if args.resume else None
    print(f"이어 돌리기: {resume.name if resume else '없음(처음부터)'}", flush=True)
    started = time.time()
    trainer.train(resume_from_checkpoint=str(resume) if resume else None)
    seconds = time.time() - started
    steps_run = trainer.state.global_step - (int(resume.name.removeprefix("checkpoint-")) if resume else 0)
    if not trainer.is_world_process_zero():
        return 0
    model.save_pretrained(out / "adapter")
    tok.save_pretrained(out / "adapter")

    import peft
    import transformers
    manifest = json.loads((data / "manifest.json").read_text("utf-8")) if (data / "manifest.json").exists() else None
    run = {"finishedAt": datetime.now(timezone.utc).isoformat(), "seconds": round(seconds),
           "resumedFrom": resume.name if resume else None,
           "baseModel": args.base_model, "revision": revision, "args": {k: v for k, v in vars(args).items()
                                                                       if k not in ("data", "out")},
           "data": {"manifest": manifest, "encode": summary}, "repoCommit": git_commit(),
           "versions": {"python": platform.python_version(), "torch": torch.__version__,
                        "transformers": transformers.__version__, "peft": peft.__version__},
           "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
           "computeDtype": str(compute).removeprefix("torch."), "devices": devices,
           "placement": args.placement, "processes": trainer.args.world_size, "gatedDeltaBackend": backend,
           "secondsPerStep": round(seconds / max(steps_run, 1), 1),
           # 이 프로세스(0번)가 잰 값. 데이터 병렬이면 다른 GPU도 비슷합니다
           "peakMemoryGB": {i: round(torch.cuda.max_memory_allocated(i) / 2**30, 2)
                            for i in range(torch.cuda.device_count())},
           "trainablePercent": round(100 * trainable / total, 3), "log": trainer.state.log_history}
    (out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"어댑터 {out / 'adapter'}, 기록 {out / 'run.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
