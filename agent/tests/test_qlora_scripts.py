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


# ---------- v6: 변환 기록과 PEFT 서버(#551) ----------

def test_run_logged_keeps_whole_output_and_raises_with_tail(tmp_path: Path) -> None:
    import export_ollama

    log = tmp_path / "convert.log"
    script = "import sys\nfor i in range(100): print('줄', i)\nprint('변환 오류', file=sys.stderr)\nsys.exit(3)"
    with pytest.raises(export_ollama.ConvertError) as e:
        export_ollama.run_logged([sys.executable, "-c", script], log, tail=5)
    text = log.read_text("utf-8")
    assert "줄 0" in text and "변환 오류" in text  # 앞부분과 stderr 모두 남음
    assert "종료 코드 3" in str(e.value) and "변환 오류" in str(e.value) and "줄 0\n" not in str(e.value)
    export_ollama.run_logged([sys.executable, "-c", "print('ok')"], log)  # 성공이면 예외 없음
    assert "ok" in log.read_text("utf-8")


def test_export_returns_2_when_conversion_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    import export_ollama

    def boom(*a: object) -> Path:
        raise export_ollama.ConvertError("종료 코드 1, 기록 x(끝 1줄):\nKeyError: 'model.language_model'")

    monkeypatch.setattr(export_ollama, "convert", boom)
    assert export_ollama.main(["--run", str(tmp_path), "--llama-cpp", "x", "--ollama", "http://127.0.0.1:9"]) == 2
    assert "GGUF 변환 실패" in capsys.readouterr().err


TOOLS = [{"type": "function", "function": {"name": "leave_request", "parameters": {"type": "object", "properties": {
    "startDate": {"type": "string"}, "days": {"type": "number"}, "half": {"type": "boolean"},
    "note": {"type": "string"}}}}}]


def test_parse_completion_tool_call_after_thinking() -> None:
    import serve_peft

    text = ("휴가 신청이니 leave_request를 부릅니다.\n</think>\n\n<tool_call>\n<function=leave_request>\n"
            "<parameter=startDate>\n2026-12-01\n</parameter>\n<parameter=days>\n2\n</parameter>\n"
            "<parameter=half>\nFalse\n</parameter>\n<parameter=note>\n123\n</parameter>\n</function>\n</tool_call><|im_end|>")
    msg = serve_peft.parse_completion(text, TOOLS)
    assert msg["content"] == ""
    (call,) = msg["tool_calls"]
    assert call["function"]["name"] == "leave_request"
    # 스키마가 string이면 숫자처럼 보여도 글 그대로, number·boolean은 JSON으로 읽습니다
    assert json.loads(call["function"]["arguments"]) == {"startDate": "2026-12-01", "days": 2, "half": False,
                                                         "note": "123"}


def test_parse_completion_plain_answer_and_unknown_tool() -> None:
    import serve_peft

    assert serve_peft.parse_completion("\n\n몇 일부터 쉬실지 알려 주세요.<|im_end|>", TOOLS) == \
        {"role": "assistant", "content": "몇 일부터 쉬실지 알려 주세요."}
    msg = serve_peft.parse_completion("<tool_call>\n<function=ticket_get>\n<parameter=id>\nT-1\n</parameter>\n"
                                      "</function>\n</tool_call>", TOOLS)
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"id": "T-1"}  # 스키마 없으면 JSON 시도 후 글


def test_normalize_messages_and_thinking_kwargs() -> None:
    import serve_peft

    msgs = serve_peft.normalize_messages([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c", "type": "function", "function": {"name": "a", "arguments": '{"x": 1}'}}]}])
    assert msgs[0]["content"] == "" and msgs[0]["tool_calls"][0]["function"]["arguments"] == {"x": 1}
    assert serve_peft.thinking_kwargs({"reasoning_effort": "none"}) == {"enable_thinking": False}
    assert serve_peft.thinking_kwargs({"reasoning_effort": "low"}) == {"enable_thinking": True}
    assert serve_peft.thinking_kwargs({}) == {}


def test_serve_peft_http_with_fake_engine() -> None:
    import threading
    from http.server import ThreadingHTTPServer

    import httpx
    import serve_peft

    class Fake:
        def chat(self, body: dict) -> dict:
            if body.get("model") not in serve_peft.MODELS:
                raise ValueError("model")
            msg = serve_peft.parse_completion("<tool_call>\n<function=leave_request>\n<parameter=days>\n1\n"
                                              "</parameter>\n</function>\n</tool_call>", body.get("tools"))
            return serve_peft.completion(body["model"], msg, 10, 5, False)

    server = ThreadingHTTPServer(("127.0.0.1", 0), serve_peft.handler(Fake()))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        with httpx.Client() as c:
            assert [m["id"] for m in c.get(url + "/models").json()["data"]] == ["base", "lora"]
            r = c.post(url + "/chat/completions", json={"model": "lora", "messages": [], "tools": TOOLS}).json()
            assert r["choices"][0]["finish_reason"] == "tool_calls"
            assert r["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] == '{"days": 1}'
            assert c.post(url + "/chat/completions", json={"model": "x", "messages": []}).status_code == 400
    finally:
        server.shutdown()


def test_qwen35_template_round_trip() -> None:
    # 학습 환경(transformers, 받아 둔 Qwen3.5 토크나이저)에서만 돕니다. template이 그린 도구 호출을 해석기가 되읽는지 봅니다
    transformers = pytest.importorskip("transformers")
    import serve_peft

    try:
        tok = transformers.AutoTokenizer.from_pretrained("Qwen/Qwen3.5-9B", local_files_only=True)
    except OSError:
        pytest.skip("Qwen3.5 토크나이저가 캐시에 없음")
    call = {"type": "function", "function": {"name": "leave_request",
                                             "arguments": {"startDate": "2026-12-01", "days": 2, "half": False}}}
    msgs = [{"role": "user", "content": "휴가"}, {"role": "assistant", "content": "", "tool_calls": [call]}]
    prompt = tok.apply_chat_template(msgs[:1], tools=TOOLS, add_generation_prompt=True, tokenize=False,
                                     enable_thinking=False)
    full = tok.apply_chat_template(msgs, tools=TOOLS, tokenize=False, enable_thinking=False)
    assert '"name": "leave_request"' in prompt  # OpenAI 형식 tools를 그대로 그림
    msg = serve_peft.parse_completion(full[len(prompt):], TOOLS)
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == call["function"]["arguments"]
