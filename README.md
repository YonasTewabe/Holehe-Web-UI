# OSINT Suite

A browser-based frontend combining [Holehe](https://github.com/megadose/holehe) and [User Scanner](https://github.com/WildSiphon/user-scanner) — check which platforms an email address or username is registered on.

## Features

### Holehe (email lookup)
- Check an email address against hundreds of platforms via the `holehe` CLI
- Real-time streaming results as they come in
- Filter to confirmed accounts only, or show all results
- Export as JSON or TXT

### User Scanner (email & username lookup)
- Scan a username or email across a wide range of sites, grouped by category
- Switch between email mode and username mode
- Live progress bar with running counts (found, errors, skipped)
- Optional: include "loud" modules (ones that notify the target site or account)
- Export as JSON, CSV, or TXT

### General
- Dark UI, runs entirely locally

## Requirements

- Docker, **or** Python 3.11+ with `pip`

## Run with Docker

```bash
docker build -t osint-suite .
docker run --rm -p 5000:5000 osint-suite
```

Open [http://localhost:5000](http://localhost:5000).

## Run without Docker

```bash
pip install -r requirements.txt
python app.py
```

Then open [http://localhost:5000](http://localhost:5000).