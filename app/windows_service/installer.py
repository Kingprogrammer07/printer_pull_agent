import sys

import win32service
import win32serviceutil

from app.core.config import settings
from app.windows_service.service import PDFPrintQueueService


def configure_service() -> None:
    try:
        win32serviceutil.ChangeServiceConfig(
            None,
            settings.service_name,
            startType=win32service.SERVICE_AUTO_START,
            delayedstart=True,
        )
        win32serviceutil.SetServiceCustomOption(settings.service_name, "FailureActionsOnNonCrashFailures", 1)
    except Exception:
        pass


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(PDFPrintQueueService)
    if len(sys.argv) > 1 and sys.argv[1].lower() == "install":
        configure_service()

