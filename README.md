# OSINT Suite

A browser-based intelligence tool combining [Holehe](https://github.com/megadose/holehe) and [User Scanner](https://github.com/kaifcodec/user-scanner) — check which platforms an email address or username is registered on, with a clean dark UI, user accounts, and saved searches.

---

## Features

### Holehe — email lookup
- Check an email address against hundreds of platforms via the `holehe` CLI
- Filter to confirmed accounts only
- Export report as JSON or TXT

### User Scanner — email & username lookup
- Scan a username or email across a wide range of sites
- Switch between **Email** and **Username** mode
- Live progress bar with running counts (found, scanned, errors, skipped)
- Optionally include "loud" modules (ones that may notify the target)
- Export report as JSON, CSV, or TXT

### Accounts & saved searches
- Register and log in to save searches for quick re-running
- Saved searches shown in a sidebar — click to re-run, × to delete
- Sessions expire after a configurable period (default 8 hours)

---

## Requirements

- Python 3.11+
- PostgreSQL
- Docker (optional)

---

## Setup

### 1. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```dotenv
# Flask
SECRET_KEY=your-secret-key-change-in-production

# PostgreSQL connection string
DATABASE_URL=postgresql://user:password@localhost/osint_suite

# Session lifetime in hours (default: 8)
SESSION_HOURS=8
```

### 2. Run with Docker

```bash
docker build -t osint-suite .
docker run --rm -p 5000:5000 --env-file .env osint-suite
```

### 3. Run without Docker

```bash
pip install -r requirements.txt
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

---

## Configuration

| Variable       | Default                                           | Description                              |
|----------------|---------------------------------------------------|------------------------------------------|
| `SECRET_KEY`   | `dev-secret-key-change-in-production`             | Flask session signing key                |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost/osint_suite` | PostgreSQL connection string        |
| `SESSION_HOURS`| `8`                                               | How long a login session lasts (hours)   |

---

## Stack

- **Backend** — Flask, Flask-Login, Flask-Bcrypt, Flask-SQLAlchemy, psycopg3
- **Database** — PostgreSQL
- **Scan engines** — [holehe](https://github.com/megadose/holehe), [user-scanner](https://github.com/kaifcodec/user-scanner)
- **Frontend** — Vanilla HTML/CSS/JS, dark theme, SSE for real-time streaming
