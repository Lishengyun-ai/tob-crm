"""Windows Service wrapper for the local AI CRM backend.

The service hosts the existing ``server.py`` HTTP handler in-process so the
Windows Service Control Manager can start and stop it reliably.  No third
party service wrapper is required; ``pywin32`` is already part of the
project's Anaconda runtime.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import servicemanager
import win32event
import win32service
import win32serviceutil


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AICrm8877Service(win32serviceutil.ServiceFramework):
    _svc_name_ = "AICrm8877"
    _svc_display_name_ = "AI CRM 8877 Backend"
    _svc_description_ = "Runs the AI CRM backend on the local network at port 8877."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.http_server = None
        self.server_thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.http_server is not None:
            self.http_server.shutdown()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        try:
            os.chdir(ROOT)
            os.environ.setdefault("PORT", "8877")

            import server as crm_server

            crm_server.init_db()
            port = int(os.environ["PORT"])
            self.http_server = crm_server.ThreadingHTTPServer(
                ("0.0.0.0", port), crm_server.Handler
            )
            self.server_thread = threading.Thread(
                target=self.http_server.serve_forever,
                name="crm-http-server",
                daemon=True,
            )
            self.server_thread.start()
            servicemanager.LogInfoMsg(
                f"AI CRM backend started on port {port} from {ROOT}"
            )
            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        except Exception as exc:  # service failures must reach the Event Log
            servicemanager.LogErrorMsg(f"AI CRM backend failed to start: {exc!r}")
            raise
        finally:
            if self.http_server is not None:
                self.http_server.server_close()
            if self.server_thread is not None:
                self.server_thread.join(timeout=5)


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(AICrm8877Service)
