from __future__ import annotations

from incident.collect import filter_jsonl, parse_time, sort_log
from incident.run import dotenv
from incident.stack import session_env


def test_filter_jsonl_keeps_window_only() -> None:
    text = "\n".join([
        '{"occurredAt": "2026-11-21T01:00:00+09:00", "kind": "a"}',
        '{"occurredAt": "2026-11-21T01:05:00+09:00", "kind": "b"}',
        'not json',
        '{"occurredAt": "2026-11-20T16:10:00Z", "kind": "c"}',
    ])
    kept = filter_jsonl(text, parse_time("2026-11-21T01:01:00+09:00"), parse_time("2026-11-21T01:10:00+09:00"))
    assert [line.split('"kind": ')[1] for line in kept.splitlines()] == ['"b"}', '"c"}']


def test_sort_log_merges_by_timestamp_and_keeps_continuations() -> None:
    text = "\n".join([
        "2026-11-20T16:00:02.000000000Z b",
        "2026-11-20T16:00:01.000000000Z a",
        "\tat java.lang.Thread.run",
    ])
    assert sort_log(text).splitlines() == [
        "2026-11-20T16:00:01.000000000Z a", "\tat java.lang.Thread.run", "2026-11-20T16:00:02.000000000Z b"]


def test_session_ports_follow_docs() -> None:
    env = session_env(1)
    assert env["COMPOSE_PROJECT_NAME"] == "iaa-s1"
    assert (env["PORT_ERP"], env["PORT_GATEWAY"], env["PORT_POSTGRES"]) == ("8140", "8110", "8160")


def test_dotenv(tmp_path) -> None:
    p = tmp_path / ".env"
    p.write_text("# c\nA=1\nB='x=y'\n", encoding="utf-8")
    assert dotenv(p) == {"A": "1", "B": "x=y"}
