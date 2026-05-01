import asyncio
import os
import threading
import traceback

import servicemanager
import win32event
import win32service
import win32serviceutil

from app.agent.client import LocalPrintAgent
from app.core.config import settings


class PDFPrintAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = f"{settings.service_name}Agent"
    _svc_display_name_ = "PDF Print Queue Local Agent"
    _svc_description_ = "Connects to the cloud print queue and prints jobs on the local Windows printer."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.loop = None
        self.task = None
        self.thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self.thread = threading.Thread(target=self.main, name="PDFPrintAgent", daemon=True)
        self.thread.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def main(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(LocalPrintAgent().run_forever())
        try:
            self.loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except Exception:
            servicemanager.LogErrorMsg(traceback.format_exc())
        finally:
            self.loop.close()


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PDFPrintAgentService)
