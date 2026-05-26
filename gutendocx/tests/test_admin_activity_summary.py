import json
import time

from gutendocx.web import server


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            if row == "__INVALID__":
                f.write("{not-json\n")
            else:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_activity_summary_counts_jobs_files_costs_and_errors(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit_events.jsonl"
    costs_path = tmp_path / "ai_costs.jsonl"
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()

    now = int(time.time())
    job_id = "job_test_1"
    batch_id = "batch_test"
    job = {
        "id": job_id,
        "type": "apply",
        "status": "completed",
        "created_at": (now - 60) * 1000,
        "started_at": (now - 55) * 1000,
        "finished_at": (now - 10) * 1000,
        "request_summary": {
            "batch_id": batch_id,
            "batch_count": 3,
            "options": {
                "apply_body": True,
                "apply_cover": False,
                "update_toc": True,
                "toc_mode": "structured",
                "vision": True,
            },
        },
        "files": [
            {"name": "a.docx", "path": "Uploads/batch_test/a.docx", "status": "completed"},
            {"name": "b.docx", "path": "Uploads/batch_test/b.docx", "status": "completed"},
            {"name": "c.docx", "path": "Uploads/batch_test/c.docx", "status": "failed"},
        ],
        "ai_cost": {"total_usd": 0.125},
        "download": {"url": "/output/batch_test.zip"},
    }
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job), encoding="utf-8")

    _write_jsonl(
        audit_path,
        [
            {
                "ts": now - 50,
                "event": "job.apply.created",
                "job_id": job_id,
                "cf_access_user": "client@example.com",
            },
            {
                "ts": now - 20,
                "event": "job.file.failed",
                "job_id": job_id,
                "batch_id": batch_id,
                "input": {"name": "c.docx"},
                "error_type": "ValueError",
                "error": "sample failure",
            },
            "__INVALID__",
        ],
    )
    _write_jsonl(
        costs_path,
        [
            {
                "ts": now - 40,
                "model": "gpt-4o-mini",
                "kind": "cover_vision",
                "batch_id": batch_id,
                "input_path": "Uploads/batch_test/a.docx",
                "input_tokens": 1000,
                "output_tokens": 100,
                "total_tokens": 1100,
                "cost_usd": 0.001,
            }
        ],
    )

    monkeypatch.setattr(server, "AUDIT_EVENTS_JSONL", str(audit_path))
    monkeypatch.setattr(server, "AI_COSTS_JSONL", str(costs_path))
    monkeypatch.setattr(server, "JOBS_DIR", str(jobs_dir))

    summary = server._activity_summary(days=30, recent_limit=5, error_limit=5)

    assert summary["totals"]["jobs"] == 1
    assert summary["totals"]["files_total"] == 3
    assert summary["totals"]["files_completed"] == 2
    assert summary["totals"]["files_failed"] == 1
    assert summary["totals"]["ai_calls"] == 1
    assert summary["totals"]["files_with_ai_cost_events"] == 1
    assert summary["totals"]["files_completed_without_ai_cost_events"] == 1
    assert summary["option_counts"]["apply_body"] == 1
    assert summary["option_counts"]["update_toc"] == 1
    assert summary["by_toc_mode"]["structured"] == 1
    assert summary["recent_jobs"][0]["actor_email"] == "client@example.com"
    assert summary["recent_jobs"][0]["duration_ms"] == 45_000
    assert summary["recent_errors"][0]["summary"] == "sample failure"
    assert summary["audit_health"]["audit_events"]["invalid"] == 1


def test_audit_event_adds_schema_source_and_operation(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit_events.jsonl"
    monkeypatch.setattr(server, "AUDIT_EVENTS_JSONL", str(audit_path))

    server._audit_event("client.apply_error", None, error="cloudflare timeout")

    row = json.loads(audit_path.read_text(encoding="utf-8").strip())
    assert row["schema_version"] == server.AUDIT_SCHEMA_VERSION
    assert row["source"] == "client"
    assert row["operation"] == "apply_error"
    assert row["event"] == "client.apply_error"
    assert row["error"] == "cloudflare timeout"


def test_ai_usage_cost_event_includes_context(tmp_path, monkeypatch):
    costs_path = tmp_path / "ai_costs.jsonl"
    monkeypatch.setattr(server, "AI_COSTS_JSONL", str(costs_path))
    server.JOB_CONTEXT.job_id = "job_cost_test"
    try:
        totals = server._new_ai_totals()
        server._record_result_ai_usage(
            totals,
            {"detection": {"ai_usage": {"model": "gpt-4o-mini", "input_tokens": 1000, "output_tokens": 100}}},
            {"endpoint": "/cover/analyze", "batch_id": "batch_cost", "input_path": "Uploads/batch_cost/a.docx", "kind": "cover_vision"},
        )
    finally:
        server.JOB_CONTEXT.job_id = None

    row = json.loads(costs_path.read_text(encoding="utf-8").strip())
    assert row["schema_version"] == server.AUDIT_SCHEMA_VERSION
    assert row["operation"] == "ai_call"
    assert row["status"] == "completed"
    assert row["job_id"] == "job_cost_test"
    assert row["endpoint"] == "/cover/analyze"
    assert row["kind"] == "cover_vision"
    assert row["total_tokens"] == 1100
    assert totals["total_tokens"] == 1100
