import importlib.util
import sys

from harness.paths import EVAL_DIR

spec = importlib.util.spec_from_file_location("router_report", EVAL_DIR / "tools" / "router_report.py")
rr = importlib.util.module_from_spec(spec)
sys.modules["router_report"] = rr
spec.loader.exec_module(rr)
MODES = {"assistant": "external_allowed", "hr": "local_only", "finance": "local_only"}


def row(i, rep, expected, agent, method="llm", source="normal", fallback=False, confidence=1.0, ms=1000):
    return {"id": f"s{i}", "repeat": rep, "expected": expected, "agent": agent, "method": method, "source": source,
            "fallback": fallback, "confidence": confidence, "latencyMs": ms}


def test_summary_counts_leaks_ambiguous_and_repeats():
    rows = [row(1, 1, "hr", "hr"), row(1, 2, "hr", "assistant"), row(2, 1, "assistant", "assistant"),
            row(2, 2, "assistant", "assistant", fallback=True), row(3, 1, "hr", "assistant", source="router_stage2")]
    m = rr.method_summary(rows, MODES)
    assert m["accuracy"]["n"] == 3 and m["accuracy"]["N"] == 5
    assert m["leaks"] == 2 and m["ambiguous"] == 1 and m["leaksIfAmbiguousLocal"] == 2
    assert m["allRepeats"]["n"] == 1 and m["unstable"] == 1
    assert m["bySource"]["router_stage2"] == {"n": 0, "N": 1, "rate": 0.0, "low": 0.0, "high": m["bySource"]["router_stage2"]["high"]}
    assert m["confusion"]["hr→assistant"] == 2


def test_probability_methods_use_confidence_threshold():
    rows = [row(1, 1, "hr", "assistant", method="laya", confidence=0.3),
            row(2, 1, "hr", "assistant", method="laya", confidence=0.9)]
    m = rr.method_summary(rows, MODES, threshold=0.5)
    assert m["ambiguous"] == 1 and m["leaks"] == 2 and m["leaksIfAmbiguousLocal"] == 1


def test_render_pairs_llm_with_others():
    llm = [row(i, 1, "hr", "hr") for i in range(4)]
    kw = [row(i, 1, "hr", "hr" if i < 2 else "assistant", method="keyword") for i in range(4)]
    md = rr.render({"llm": llm, "keyword": kw}, MODES, {"llm": "a.jsonl", "keyword": "b.jsonl"})
    assert "llm − keyword: +50.0%p" in md and "| llm(`a.jsonl`) | 4/4" in md
