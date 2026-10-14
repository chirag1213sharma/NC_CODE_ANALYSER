# NC Code Analyser — Linux Deployment Guide

Deploy the analyser on a Linux server so multiple QA users on the same
network can use the web UI concurrently and submit feedback.

---

## 1. What gets installed

| Component | Purpose | How it runs |
|---|---|---|
| FastAPI app (`src.main:app`) | REST API + serves `frontend/index.html` | `systemd` unit `nc-analyser.service` |
| Uvicorn (single async worker) | ASGI server, binds `0.0.0.0:8000` | child of the systemd unit |
| Ollama | Local LLM backend (used by `OllamaClassifier`) | `systemd` unit `ollama.service` |
| `data/` + `feedback.json` | Uploads, baselines, reports, QA feedback | on disk, owned by `ncanalyser` user |

> **Why a single uvicorn worker?**
> [src/api/routes/files.py](src/api/routes/files.py#L26) and
> [src/api/routes/compare.py](src/api/routes/compare.py#L24) keep state in
> process-local dicts (`file_registry`, `analysis_registry`). Running multiple
> workers would split that state and break uploads/compare flows. The app is
> fully `async`, so one worker still serves many simultaneous QA users for this
> I/O-bound workload. If you later move the registries to Redis/Postgres you
> can scale `--workers` up.

---

## 2. One-shot install (Ubuntu / Debian)

Copy the repo to the target machine (e.g. `scp -r` or `git clone`) and run:

### Run these commands for installation deploy and collect feedback.
```bash
cd /home/gtuser/CAMWorksDocuments/Automation/CW-Automation/NC_CODE_ANALYSER
sudo bash deploy/sync-feedback.sh
sudo bash deploy/setup.sh
sudo systemctl restart nc-analyser
```

The script will:

1. Install system packages (Python, libmagic, Pango/Cairo for WeasyPrint, etc.)
2. Create a dedicated `ncanalyser` system user
3. Sync the source into `/opt/nc-code-analyser`
4. Create a Python virtualenv and install [requirements-linux.txt](requirements-linux.txt)
5. Install Ollama and pull the default model (`mistral`, override with `OLLAMA_MODEL=...`)
6. Install and start `nc-analyser.service`

When it finishes it prints the LAN URL, e.g. `http://192.168.1.42:8000/`.

### Override defaults

```bash
sudo APP_DIR=/srv/nc OLLAMA_MODEL=qwen2.5-coder:7b bash deploy/setup.sh
```

---

## 3. Manual install (any distro)

```bash
# 3.1 System packages (Debian/Ubuntu shown; use dnf/yum equivalents elsewhere)
sudo apt-get install -y python3 python3-venv python3-dev build-essential \
    libmagic1 libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info

# 3.2 Python env
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements-linux.txt

# 3.3 Ollama
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
ollama pull mistral          # or whatever you set in .env

# 3.4 Config
cp .env.example .env
$EDITOR .env                 # set OLLAMA_MODEL, DEBUG=false, etc.

# 3.5 Run
bash deploy/run-dev.sh       # foreground, good for first smoke test
```

For continuous operation, install the systemd unit:

```bash
sudo cp deploy/nc-analyser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nc-analyser
```

---

## 4. Configuration (`/opt/nc-code-analyser/.env`)

The only values that matter for a Linux deployment:

| Variable | Recommended value | Notes |
|---|---|---|
| `HOST` | `0.0.0.0` | bind on all interfaces (already the default) |
| `PORT` | `8000` | open this port in the firewall |
| `DEBUG` | `false` | disables auto-reload |
| `LOG_LEVEL` | `INFO` | `DEBUG` is very verbose |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama runs on the same host |
| `OLLAMA_MODEL` | `mistral` (or `qwen2.5-coder:7b`) | must be pulled via `ollama pull` |
| `UPLOAD_DIR` / `BASELINE_DIR` / `REPORTS_DIR` | leave defaults | created at startup |

> `DATABASE_URL*` is in the settings but the current code does not use
> Postgres — feedback is stored in `feedback.json`. You can ignore these
> values until DB persistence is added.

After editing `.env`:

```bash
sudo systemctl restart nc-analyser
```

---

## 5. Network access for QA users

Open port 8000 (or whatever you set):

```bash
# ufw (Ubuntu)
sudo ufw allow 8000/tcp

# firewalld (RHEL/Fedora)
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

QA users browse to `http://<server-ip>:8000/`.

### Optional: put nginx in front (clean URL + TLS)

```nginx
# /etc/nginx/sites-available/nc-analyser
server {
    listen 80;
    server_name nc-analyser.local;

    client_max_body_size 50M;          # NC files can be large

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/nc-analyser /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Add TLS later with `sudo certbot --nginx`.

---

## 6. Operating the service

```bash
sudo systemctl status nc-analyser     # is it up?
sudo systemctl restart nc-analyser    # after editing .env or pulling new code
sudo journalctl -u nc-analyser -f     # live logs
sudo journalctl -u ollama -f          # Ollama logs
```

Updating to a new code version:

```bash
cd /path/to/checkout
git pull
sudo rsync -a --delete \
    --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
    --exclude 'data/' --exclude '.env' --exclude 'feedback.json' \
    ./ /opt/nc-code-analyser/
sudo -u ncanalyser /opt/nc-code-analyser/.venv/bin/pip install -r /opt/nc-code-analyser/requirements-linux.txt
sudo systemctl restart nc-analyser
```

---

## 7. Concurrency model — what to expect

* Multiple QA users can upload, compare, view reports and submit feedback at
  the same time. The async event loop interleaves their requests.
* `FeedbackStore.add_feedback` already uses a `threading.Lock` around the
  `feedback.json` read/write, so concurrent QA submissions are safe within
  the single worker process. See
  [src/feedback/feedback_store.py](src/feedback/feedback_store.py#L42-L102).
* The slow part of any request is the Ollama call. Ollama serialises
  inference per model, so two simultaneous compares will be processed
  back-to-back, not in parallel. If you need parallel inference, run a
  larger model on GPU and accept the queueing, or pull a smaller model.
* If you ever need to scale beyond one process, replace the in-memory
  registries in [files.py](src/api/routes/files.py#L26) and
  [compare.py](src/api/routes/compare.py#L24) with Redis / a database,
  then raise `--workers` in [nc-analyser.service](deploy/nc-analyser.service).

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: failed to find libmagic` | `sudo apt-get install libmagic1` (already in `setup.sh`) |
| `WeasyPrint` complains about Pango/Cairo | install the `libpango*` / `libcairo2` packages from §3.1 |
| AI classification always says "AI unavailable" | `systemctl status ollama`; verify `OLLAMA_MODEL` matches `ollama list` |
| QA users get connection refused | check firewall (`ufw status`), confirm `HOST=0.0.0.0` |
| Service won't start, `Permission denied` on `data/` | `sudo chown -R ncanalyser:ncanalyser /opt/nc-code-analyser` |
