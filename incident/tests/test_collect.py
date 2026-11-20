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


def test_logs_before_and_after_recovery_are_joined(tmp_path) -> None:
    from datetime import datetime, timezone

    from incident.collect import collect

    class FakeStack:
        erp_url = "http://localhost:1/api/v1"

        def logs(self, svc, since, until):
            return f"2026-11-20T16:12:00.000000000Z {svc} new container\n"

        def audit_lines(self):
            return {}

    t0 = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 20, 16, 10, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 20, 16, 13, tzinfo=timezone.utc)
    earlier = {"gateway": "2026-11-20T16:05:00.000000000Z gateway old container 401\n"}
    collect(FakeStack(), tmp_path, t0, t2, "E0057", "x", earlier, t1)
    lines = (tmp_path / "logs" / "gateway.log").read_text().splitlines()
    assert lines == ["2026-11-20T16:05:00.000000000Z gateway old container 401",
                     "2026-11-20T16:12:00.000000000Z gateway new container"]


def test_container_events_drop_exec_and_convert_time() -> None:
    from incident.stack import Stack

    class Proc:
        def terminate(self):
            pass

        def communicate(self, timeout=None):
            return ("1795190820000000000 exec_start: sh -c pg_isready postgres exitCode=<no value>\n"
                    "1795190820500000000 oom erp exitCode=<no value>\n"
                    "1795190821000000000 die erp exitCode=137\n", "")

    assert Stack.stop_events(Proc()).splitlines() == [
        "2026-11-20T16:07:00.500000Z oom erp", "2026-11-20T16:07:01.000000Z die erp exitCode=137"]
