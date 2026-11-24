"""PEFT 어댑터를 transformers로 직접 띄우는 작은 OpenAI 호환 서버(#551 v6). GGUF 변환이 안 될 때 개발 묶음 비교용입니다.

기본 모델을 학습 때처럼 4비트(NF4)로 한 번 올리고 어댑터를 얹습니다. 요청의 `model`이 `lora`면 어댑터를 켜고,
`base`면 어댑터를 끈 채(같은 4비트 기본 모델) 답합니다. 그래서 기본·LoRA를 같은 런타임에서 견줍니다. Ollama(GGUF Q4_K_M)
수치와는 런타임이 달라 직접 비교하지 않습니다.

- `POST /v1/chat/completions`: messages, tools(OpenAI 형식), max_tokens, reasoning_effort(`none`이면 생각 끔, 그 밖의 값이면
  켬, 없으면 chat template 기본값인 켬). temperature는 무시하고 항상 greedy입니다(평가 실행기는 0을 보냄)
- `GET /v1/models`: 준비 확인
- 답의 `<think>…</think>`는 버리고, `<tool_call><function=…><parameter=…>` 블록을 OpenAI `tool_calls`로 바꿉니다
  (Qwen3.5 chat template 형식). 인자 값은 도구 스키마의 type이 string이면 글 그대로, boolean이면 true·false(대소문자
  무시), 그 밖에는 JSON으로 읽습니다
- 생성은 한 번에 하나씩 합니다(잠금)

    python lora/serve_peft.py --adapter <run>/adapter --port 8001
    uv run python eval_dev/first_call_run.py --base-url http://127.0.0.1:8001/v1 --model lora --out …
"""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

TOOL_CALL = re.compile(r"<tool_call>\s*<function=([^>\n]+)>(.*?)</function>\s*</tool_call>", re.S)
PARAM = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)
END_MARKS = ("<|im_end|>", "<|endoftext|>")
MODELS = ("base", "lora")


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI 메시지를 chat template에 맞춥니다. assistant tool_calls의 arguments(JSON 글)를 객체로, content None을 ""로."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get("content") is None:
            m["content"] = ""
        if m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                fn = dict(c.get("function", c))
                if isinstance(fn.get("arguments"), str):
                    try:
                        fn["arguments"] = json.loads(fn["arguments"] or "{}")
                    except json.JSONDecodeError:
                        fn["arguments"] = {}
                calls.append({**c, "function": fn})
            m["tool_calls"] = calls
        out.append(m)
    return out


def thinking_kwargs(body: dict[str, Any]) -> dict[str, Any]:
    """reasoning_effort → chat template enable_thinking. 없으면 넘기지 않습니다(template 기본값: 켬)."""
    effort = body.get("reasoning_effort")
    if effort is None:
        return {}
    return {"enable_thinking": str(effort).lower() != "none"}


def _param_types(tools: list[dict[str, Any]] | None) -> dict[str, dict[str, str]]:
    types: dict[str, dict[str, str]] = {}
    for t in tools or []:
        fn = t.get("function", t)
        props = (fn.get("parameters") or {}).get("properties") or {}
        types[fn.get("name", "")] = {k: str((v or {}).get("type", "")) for k, v in props.items()}
    return types


def _value(raw: str, kind: str) -> Any:
    if kind == "string":
        return raw
    if kind == "boolean" and raw.strip().lower() in ("true", "false"):
        return raw.strip().lower() == "true"  # template은 파이썬 불 값을 True·False로 그립니다
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_completion(text: str, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """생성 글을 OpenAI assistant 메시지로. 생각은 버리고 도구 호출 블록을 tool_calls로, 나머지를 content로."""
    for mark in END_MARKS:
        text = text.split(mark)[0]
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    types = _param_types(tools)
    calls = []
    for i, m in enumerate(TOOL_CALL.finditer(text)):
        name = m.group(1).strip()
        kinds = types.get(name, {})
        args = {p.group(1).strip(): _value(p.group(2), kinds.get(p.group(1).strip(), "")) for p in PARAM.finditer(m.group(2))}
        calls.append({"id": f"call_{i}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    content = TOOL_CALL.sub("", text).strip()
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = calls
    return msg


def completion(model: str, msg: dict[str, Any], prompt_tokens: int, completion_tokens: int, hit_limit: bool) -> dict:
    finish = "tool_calls" if msg.get("tool_calls") else ("length" if hit_limit else "stop")
    return {"id": "chatcmpl-" + uuid.uuid4().hex[:12], "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}


class Engine:
    """4비트 기본 모델 + PEFT 어댑터. generate는 잠금 안에서 한 번에 하나씩 돕니다."""

    def __init__(self, adapter: Path, base_model: str | None, revision: str | None, max_new: int, max_new_think: int):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

        cfg = json.loads((adapter / "adapter_config.json").read_text("utf-8"))
        base_model = base_model or cfg.get("base_model_name_or_path") or "Qwen/Qwen3.5-9B"
        bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
        compute = torch.bfloat16 if bf16 else torch.float16
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(base_model, revision=revision)
        model = AutoModelForImageTextToText.from_pretrained(
            base_model, revision=revision, device_map={"": 0}, dtype=compute,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                   bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=compute))
        self.model = PeftModel.from_pretrained(model, str(adapter)).eval()
        self.max_new, self.max_new_think = max_new, max_new_think
        self.lock = threading.Lock()
        self.info = {"baseModel": base_model, "revision": revision, "adapter": str(adapter),
                     "computeDtype": str(compute).removeprefix("torch.")}

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        name = body.get("model")
        if name not in MODELS:
            raise ValueError(f"model은 {MODELS} 중 하나입니다: {name!r}")
        tools = body.get("tools") or None
        think = thinking_kwargs(body)
        enc = self.tok.apply_chat_template(normalize_messages(body["messages"]), tools=tools, add_generation_prompt=True,
                                           return_dict=True, return_tensors="pt", **think)
        enc = {k: v.to(self.model.device) for k, v in enc.items()}
        limit = self.max_new if think.get("enable_thinking") is False else self.max_new_think
        limit = min(int(body.get("max_tokens") or limit), limit)
        with self.lock, self.torch.inference_mode():
            if name == "base":
                with self.model.disable_adapter():
                    out = self.model.generate(**enc, do_sample=False, max_new_tokens=limit)
            else:
                out = self.model.generate(**enc, do_sample=False, max_new_tokens=limit)
        n_in = enc["input_ids"].shape[1]
        new = out[0][n_in:]
        text = self.tok.decode(new, skip_special_tokens=False)
        return completion(name, parse_completion(text, tools), n_in, int(new.shape[0]), int(new.shape[0]) >= limit)


def handler(engine: Any) -> type[BaseHTTPRequestHandler]:
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in MODELS]})
            else:
                self._send(404, {"error": {"message": "없는 경로"}})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/v1/chat/completions":
                self._send(404, {"error": {"message": "없는 경로"}})
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                self._send(200, engine.chat(body))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": {"message": f"{type(e).__name__}: {e}"}})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(time.strftime("%H:%M:%S"), fmt % args, flush=True)

    return H


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="PEFT 어댑터 폴더(adapter_config.json, adapter_model.safetensors)")
    ap.add_argument("--base-model", default=None, help="빼면 adapter_config.json의 base_model_name_or_path")
    ap.add_argument("--revision", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--max-new-tokens", type=int, default=512, help="생각 끔일 때 생성 상한")
    ap.add_argument("--max-new-tokens-think", type=int, default=1536, help="생각 켬일 때 생성 상한(생각 포함)")
    args = ap.parse_args(argv)
    engine = Engine(Path(args.adapter).expanduser(), args.base_model, args.revision, args.max_new_tokens,
                    args.max_new_tokens_think)
    print(json.dumps({"serving": f"http://{args.host}:{args.port}/v1", **engine.info}, ensure_ascii=False), flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(engine)).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
