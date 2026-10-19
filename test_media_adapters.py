import sqlite3
import unittest
import base64
import json
import tempfile
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from media_adapters import (
    AdapterRequest,
    MediaAdapterService,
    ensure_media_adapter_schema,
    persist_adapter_run,
    queue_fact_candidates,
)
import server


class MediaAdapterTests(unittest.TestCase):
    def test_mock_contract_and_retryable_error(self):
        service = MediaAdapterService()
        response = service.execute_with_retry(AdapterRequest("transcribe", "rec-1", "recording", payload={"text": "客户确认下月评审"}))
        self.assertEqual(response.status, "SUCCESS")
        self.assertEqual(response.output["text"], "客户确认下月评审")
        failed = service.execute_with_retry(AdapterRequest("ocr", "img-1", "image", payload={"simulateError": True, "retryable": True}, max_attempts=2))
        self.assertEqual(failed.status, "RETRYABLE")
        self.assertEqual(failed.attempt, 2)
        self.assertEqual(failed.error_code, "MOCK_OCR_FAILURE")

    def test_run_audit_and_fact_candidates_are_pending(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
          CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
          CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT);
          CREATE TABLE opportunities (id INTEGER PRIMARY KEY, name TEXT);
          CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT);
          CREATE TABLE fact_candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, fact_type TEXT, subject_type TEXT, subject_id INTEGER, predicate TEXT, object_value TEXT, object_type TEXT, source_type TEXT, source_id TEXT, confidence INTEGER, status TEXT, created_by TEXT, created_time TEXT);
        """)
        ensure_media_adapter_schema(db)
        db.execute("INSERT INTO customers VALUES (1, '客户A')")
        response = MediaAdapterService().execute(AdapterRequest("ocr", "img-1", "image", payload={"projectName": "项目A"}))
        run_id = persist_adapter_run(db, AdapterRequest("ocr", "img-1", "image", payload={"projectName": "项目A"}), response, now="2026-10-16T00:00:00+00:00")
        ids = queue_fact_candidates(db, [{"factType": "CustomerProfile", "subjectType": "Customer", "subjectId": 1, "predicate": "projectName", "value": "项目A", "confidence": 0.52}], source_type="document", source_id="img-1", now="2026-10-16T00:00:00+00:00")
        self.assertEqual(response.status, "SUCCESS")
        self.assertTrue(run_id)
        self.assertEqual(len(ids), 1)
        self.assertEqual(db.execute("SELECT status FROM fact_candidates WHERE id = ?", (ids[0],)).fetchone()[0], "PENDING")
        self.assertGreater(db.execute("SELECT COUNT(*) FROM media_audit_logs WHERE run_id = ?", (run_id,)).fetchone()[0], 0)

    def test_discovery_endpoint_keeps_adapter_run_and_requires_duplicate_check(self):
        temp_dir = tempfile.TemporaryDirectory()
        old_dir, old_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR, server.DB_PATH = Path(temp_dir.name), Path(temp_dir.name) / "crm.sqlite3"
        try:
            server.init_db()
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            payload = {"fileName": "sign.jpg", "mimeType": "image/jpeg", "contentBase64": base64.b64encode(b"fake-image").decode(), "projectName": "新项目", "customerName": "新客户", "notes": "现场牌"}
            req = Request(f"http://127.0.0.1:{httpd.server_port}/api/discovery/drafts", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            body = json.loads(urlopen(req).read())
            self.assertTrue(body["evidence"]["adapterRunId"])
            check = Request(f"http://127.0.0.1:{httpd.server_port}/api/discovery/{body['runId']}/duplicate-check", data=b"{}", headers={"Content-Type": "application/json"})
            checked = json.loads(urlopen(check).read())
            self.assertIn(checked["status"], {"clear", "possible_duplicate"})
            httpd.shutdown()
            httpd.server_close()
        finally:
            server.DB_DIR, server.DB_PATH = old_dir, old_path
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
