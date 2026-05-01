# PDF Print Queue Cloud + Local Agent

FastAPI + SQLite asosida public serverda joblarni boshqaruvchi cloud qism va Windows kompyuterda printer yonida ishlaydigan local agent.

## Cloud server

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API:

- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{id}`
- `POST /api/v1/jobs/{id}/retry`
- `POST /api/v1/jobs/{id}/cancel`
- `GET /api/v1/printer/status`
- `GET /api/v1/agents`
- `GET /api/v1/health`
- `GET /api/v1/stats`
- `GET /` dashboard

## Windows local agent

`.env` ichida:

```env
SERVER_URL=https://print.example.com
AGENT_ID=windows-agent-1
PRINTER_NAME=Xprinter XP-450B
AGENT_POLL_INTERVAL=3
```

Agentni ishga tushirish:

```powershell
python scripts\run_agent.py
```

Windows service sifatida:

```powershell
python -m app.windows_service.agent_service install
python -m app.windows_service.agent_service start
```

Printer test:

```powershell
python scripts/test_xprinter_d481b.py --status
python scripts/test_xprinter_d481b.py --print
```
