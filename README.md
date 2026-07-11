# Holehe Web UI

A browser-based frontend for [holehe](https://github.com/megadose/holehe) — check which platforms an email address is registered on, save emails for later, and export results.

## Features

- Email lookup via the `holehe` CLI
- Filter to confirmed accounts only, or show all results
- Save emails to a persistent list for quick re-scanning
- Export results as JSON or TXT
- Dark UI, runs entirely locally

## Requirements

- Docker, **or** Python 3.11+ with `pip`
- `holehe` must be available on the system PATH (installed separately or via `requirements.txt`)

## Run with Docker

```bash
docker build -t holehe-ui .
docker run --rm -p 5000:5000 -v "%cd%\holehe-data:/app/data" holehe-ui
```

On Linux/macOS use `$(pwd)` instead of `%cd%`:

```bash
docker run --rm -p 5000:5000 -v "$(pwd)/holehe-data:/app/data" holehe-ui
```

The `-v` flag mounts a local folder so saved emails survive container restarts. Open [http://localhost:5000](http://localhost:5000).

## Run without Docker

```bash
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).

## Data persistence

Saved emails are stored in `holehe-data/saved_emails.json` (or wherever `DATA_DIR` points). When running in Docker, mount that directory as a volume or the data will be lost when the container stops.

```
DATA_DIR=/some/path docker run ...
```