# Holehe Web UI

A browser-based frontend for [holehe](https://github.com/megadose/holehe) — check which platforms an email address is registered on.

## Features

- Email lookup via the `holehe` CLI
- Filter to confirmed accounts only, or show all results
- Export results as JSON or TXT
- Dark UI, runs entirely locally

## Requirements

- Docker, **or** Python 3.11+ with `pip`
- `holehe` must be available on the system PATH (installed separately or via `requirements.txt`)

## Run with Docker

```bash
docker build -t holehe-ui .
docker run --rm -p 5000:5000 holehe-ui
```

Open [http://localhost:5000](http://localhost:5000).

## Run without Docker

```bash
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).