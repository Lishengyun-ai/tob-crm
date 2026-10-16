import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import server


class Task10AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_path = server.DB_DIR, server.DB_PATH
        server.DB_DIR = Path(self.tmp.name)
        server.DB_PATH = Path(self.tmp.name) / "crm.sqlite3"
        server.init_db()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(timeout=2)
        server.DB_DIR, server.DB_PATH = self.old_dir, self.old_path
        self.tmp.cleanup()

    def request(self, method, path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = Request(self.base + path, data=body, method=method, headers={"Content-Type": "application/json"})
        with urlopen(req) as response:
            raw = response.read().decode()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            return response.status, parsed

    def test_health_static_and_governance_boundaries(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200); self.assertEqual(health["status"], "ok")
        status, policies = self.request("GET", "/api/governance/policies")
        self.assertEqual(status, 200); self.assertEqual(len(policies["operations"]), 5)
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)

        status, pending = self.request("POST", "/api/opportunities", {
            "name": "审批边界测试", "customer": "测试客户", "stage": "初步接触", "amount": 900000,
            "owner": "sales", "approvalRequired": True,
        })
        self.assertEqual(status, 202); self.assertEqual(pending["status"], "pending_approval")
        status, approved = self.request("POST", f"/api/governance/approvals/{pending['approvalRequestId']}/approve", {
            "actor": {"userId": "manager", "roles": ["approver"], "canApprove": True}
        })
        self.assertEqual(status, 200); self.assertEqual(approved["status"], "APPROVED")

        status, quality = self.request("POST", "/api/data-quality/check", {"actor": "manager"})
        self.assertEqual(status, 201); self.assertIn("issues", quality)
        status, audits = self.request("GET", "/api/governance/audit")
        self.assertEqual(status, 200); self.assertGreaterEqual(len(audits), 2)

    def test_media_endpoint_keeps_candidate_governance(self):
        status, result = self.request("POST", "/api/media/adapters/transcribe", {
            "sourceId": "acceptance-1", "fileName": "voice.wav", "contentBase64": base64.b64encode(b"voice").decode(), "text": "客户确认下月评审"
        })
        self.assertEqual(status, 201); self.assertEqual(result["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
