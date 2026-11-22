"""QLoRA 학습·평가 스크립트(#545) 중 torch 없이 도는 부분: 토큰화·정답 가림·채움, 결과 비교, 저장소 밖 출력."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

LORA = Path(__file__).resolve().parents[1] / "lora"
sys.path.insert(0, str(LORA))
import compare_runs  # noqa: E402
import qlora_data as qd  # noqa: E402
import train_qlora  # noqa: E402

ROW = {"tools": [{"type": "function", "function": {"name": "leave_get_balance", "parameters": {}}}],
       "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "연차 남았어?"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"type": "function", "function": {"name": "leave_get_balance", "arguments": {}}}]}]}


class FakeTok:
    """메시지를 글자 코드로 바꾸는 chat template 흉내. 생성 프롬프트는 '<assistant>'로 끝납니다."""

    def __init__(self, change_prefix: bool = False) -> None:
        self.change_prefix = change_prefix
        self.calls: list[dict] = []

    def apply_chat_template(self, conversation, tools=None, tokenize=True, add_generation_prompt=False, **kw):
        self.calls.append({"tools": tools, **kw})
        text = f"[tools {len(tools or [])}]"
        for m in conversation:
            body = m.get("content") or json.dumps(m.get("tool_calls"), ensure_ascii=False)
            text += f"<{m['role']}>{body}</{m['role']}>"
        if add_generation_prompt:
            text += "<assistant>" + ("x" if self.change_prefix else "")
        return [ord(ch) for ch in text]


def test_only_answer_tokens_are_trained() -> None:
    tok = FakeTok()
    e = qd.encode(ROW, tok, 10_000, {"enable_thinking": False})
    assert isinstance(e, qd.Encoded) and len(e.input_ids) == len(e.labels)
    trained = "".join(chr(t) for t, lab in zip(e.input_ids, e.labels) if lab != qd.IGNORE)
    assert trained.startswith("[{") and trained.endswith("</assistant>") and "연차" not in trained
    assert all(c["tools"] == ROW["tools"] and c["enable_thinking"] is False for c in tok.calls)


def test_too_long_and_prefix_mismatch_are_counted() -> None:
    assert qd.encode(ROW, FakeTok(), 20, {}) == "too_long"
    assert qd.encode(ROW, FakeTok(change_prefix=True), 10_000, {}) == "prefix_mismatch"
    enc, stats = qd.encode_all([ROW, ROW], FakeTok(), 10_000)
    assert stats.used == 2 and len(stats.target_tokens) == 2 and len(enc) == 2


def test_batchencoding_shape_is_accepted() -> None:
    class DictTok(FakeTok):
        def apply_chat_template(self, *a, **kw):
            return {"input_ids": super().apply_chat_template(*a, **kw)}
    assert isinstance(qd.encode(ROW, DictTok(), 10_000, {}), qd.Encoded)


def test_collate_pads_right_and_masks() -> None:
    a, b = qd.Encoded([1, 2, 3], [qd.IGNORE, 2, 3]), qd.Encoded([4], [4])
    out = qd.collate([a, b], pad_id=0)
    assert out["input_ids"] == [[1, 2, 3], [4, 0, 0]]
    assert out["attention_mask"] == [[1, 1, 1], [1, 0, 0]]
    assert out["labels"] == [[qd.IGNORE, 2, 3], [4, qd.IGNORE, qd.IGNORE]]


def test_generated_rows_encode(tmp_path: Path) -> None:
    import make_toolcall_data as gen

    from tests.conftest import PACK_DIR
    rows = gen.generate(PACK_DIR, per_tool=2, seed=1)
    enc, stats = qd.encode_all(rows, FakeTok(), 100_000)
    assert stats.used == len(rows) and stats.prefix_mismatch == 0


def test_training_output_must_be_outside_repo(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="저장소 밖"):
        train_qlora.outside_repo(train_qlora.REPO / "agent" / "var")
    assert train_qlora.outside_repo(tmp_path) == tmp_path.resolve()
    assert train_qlora.parse(["--data", "d", "--out", "o"]).base_model == "Qwen/Qwen3.5-9B"


def _run(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def test_compare_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def row(i, tool, tools, clarify=False, source="dev"):
        return {"id": i, "source": source, "tool": tool, "tools": tools, "clarify": clarify, "latencyMs": 100,
                "error": None}
    base = [row("a", None, ["x"]), row("b", "x", ["x"]), row("c", None, [], True), row("s", None, ["x"], source="scenario")]
    tuned = [row("a", "x", ["x"]), row("b", "y", ["x"]), row("c", "z", [], True), row("s", "x", ["x"], source="scenario")]
    _run(tmp_path / "b.jsonl", base)
    _run(tmp_path / "t.jsonl", tuned)
    assert compare_runs.main([str(tmp_path / "b.jsonl"), str(tmp_path / "t.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "| expectedTool | 1/2 | 1/2 |" in out and "| clarifyNoTool | 1/1 | 0/1 |" in out
    assert '"better": ["a"]' in out and '"worse": ["b"]' in out


def test_install_dry_run() -> None:
    r = subprocess.run(["bash", str(LORA / "install_qlora.sh"), "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0 and "transformers==" in r.stdout


def test_progress_line() -> None:
    assert train_qlora.progress_line(120, 2488, 0.41234, 720) == "진행 120/2488 손실 0.4123 경과 12분 남은 약 237분"
    assert train_qlora.progress_line(0, 10, None, 5) == "진행 0/10 손실 - 경과 0분 남은 약 -"
    assert train_qlora.parse(["--data", "d", "--out", "o"]).progress_minutes == 3


def test_install_system_mode_dry_run() -> None:
    import os
    r = subprocess.run(["bash", str(LORA / "install_qlora.sh"), "--dry-run"], capture_output=True, text=True,
                       env={**os.environ, "QLORA_SYSTEM": "1"})
    assert r.returncode == 0 and "torch 그대로" in r.stdout and "torch==" not in r.stdout



def test_training_kwargs_use_transformers5_names(tmp_path: Path) -> None:
    # transformers 5에는 warmup_ratio가 없습니다(#551 v2 실패). 비율은 warmup_steps에 [0, 1) 실수로 줍니다
    kw = train_qlora.training_kwargs(train_qlora.parse(["--data", "d", "--out", "o"]), tmp_path, bf16=False)
    assert "warmup_ratio" not in kw and kw["warmup_steps"] == 0.03
    assert (kw["bf16"], kw["fp16"]) == (False, True)
    assert kw["output_dir"] == str(tmp_path / "checkpoints")


def test_check_training_setup_catches_unknown_argument() -> None:
    pytest.importorskip("transformers")  # agent 환경에는 없음. 학습 환경에서만 돕니다
    assert train_qlora.check_training_setup({"warmup_ratio": 0.03}, [], []) == ["TrainingArguments에 없는 인자: warmup_ratio"]


def test_last_checkpoint_skips_incomplete(tmp_path: Path) -> None:
    assert train_qlora.last_checkpoint(tmp_path) is None
    for step, complete in ((40, True), (120, True), (160, False), (9, True)):
        d = tmp_path / "checkpoints" / f"checkpoint-{step}"
        d.mkdir(parents=True)
        if complete:
            (d / "trainer_state.json").write_text("{}")
    assert train_qlora.last_checkpoint(tmp_path).name == "checkpoint-120"


def test_timed_save_due() -> None:
    assert train_qlora.due(1000 + 25 * 60, 1000, 25) and not train_qlora.due(1000 + 60, 1000, 25)
    assert not train_qlora.due(10**9, 0, 0)  # 0이면 시간 저장 끔
    a = train_qlora.parse(["--data", "d", "--out", "o", "--resume"])
    assert a.resume and a.save_minutes == 25


def test_sync_run_copies_new_and_changed_files(tmp_path: Path) -> None:
    import functools
    import http.server
    import threading

    import sync_run

    src, dst = tmp_path / "remote", tmp_path / "local"
    (src / "checkpoints" / "checkpoint-40").mkdir(parents=True)
    (src / "run.json").write_text("{}")
    (src / "checkpoints" / "checkpoint-40" / "adapter_model.safetensors").write_bytes(b"x" * 1000)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(src))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert sync_run.main(["--url", url, "--to", str(dst), "--every", "0"]) == 0
        assert (dst / "checkpoints" / "checkpoint-40" / "adapter_model.safetensors").read_bytes() == b"x" * 1000
        import httpx
        with httpx.Client() as c:
            assert sync_run.sync_once(c, url + "/", dst) == {"downloaded": 0, "unchanged": 2}
            (src / "run.json").write_text('{"done": true}')
            assert sync_run.sync_once(c, url + "/", dst) == {"downloaded": 1, "unchanged": 1}
        assert (dst / "run.json").read_text() == '{"done": true}'
    finally:
        server.shutdown()
