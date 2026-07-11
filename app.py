import json
import os
import re
import subprocess
from datetime import datetime, timezone

from email_validator import EmailNotValidError, validate_email
from flask import Flask, Response, render_template, request

app = Flask(__name__)

# Where local data is persisted. Mount a volume to DATA_DIR so it survives
# container restarts.
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
SAVED_EMAILS_FILE = os.path.join(DATA_DIR, "saved_emails.json")

# Matches lines like:
# [+] Twitter
# [-] Adobe
# [x] Amazon
LINE_RE = re.compile(r"^\[([+\-x])\]\s+(.*)$")


def _load_json_list(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_saved_emails():
    return _load_json_list(SAVED_EMAILS_FILE)


def save_saved_emails(emails):
    _save_json(SAVED_EMAILS_FILE, emails)


def check_email(email: str, check_dns: bool = True):
    """
    Validate email syntax and, optionally, that the domain has valid mail
    servers configured (MX record check). Returns (normalized_email, error).
    """
    try:
        result = validate_email(email, check_deliverability=check_dns)
        return result.normalized, None
    except EmailNotValidError as e:
        return None, f"Invalid email: {e}"


def run_holehe(email: str, only_used: bool = True):
    """Run the holehe CLI against an email and parse the output into structured rows."""
    cmd = ["holehe", email, "-C"]  # -C disables color codes so parsing is clean
    if only_used:
        cmd.append("--only-used")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return [], "Lookup timed out. Try again."

    rows = []
    for line in result.stdout.splitlines():
        line = line.strip()

        # Skip holehe's one-time legend line, e.g.:
        # "[+] Email used, [-] Email not used, [x] Rate limit"
        # It matches the same [+]/[-]/[x] pattern as real results, so it
        # must be filtered out explicitly or it shows up as a fake "site".
        if "Email used" in line and "Email not used" in line:
            continue

        match = LINE_RE.match(line)
        if match:
            status, site = match.groups()
            site = site.strip()

            # Extra safety net: a real site name will never contain a
            # bracketed status marker like the legend does.
            if "[" in site or "]" in site:
                continue

            rows.append({"status": status, "site": site})

    error = None
    if result.returncode != 0 and not rows:
        error = result.stderr.strip() or "holehe returned no output."

    return rows, error


@app.route("/", methods=["GET", "POST"])
def index():
    rows = None
    email = ""
    only_used = False
    error = None

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        only_used = request.form.get("only_used") == "on"

        if not email:
            error = "Please enter an email address."
        else:
            normalized, validation_error = check_email(email)
            if validation_error:
                error = validation_error
            else:
                email = normalized  # use the normalized form for the actual lookup
                rows, error = run_holehe(email, only_used)

    return render_template(
        "index.html",
        rows=rows,
        rows_json=json.dumps(rows) if rows else "[]",
        email=email,
        only_used=only_used,
        error=error,
        saved_emails=load_saved_emails(),
    )


@app.route("/save-email", methods=["POST"])
def save_email():
    email = request.form.get("email", "").strip()
    if email:
        normalized, validation_error = check_email(email)
        if not validation_error:
            emails = load_saved_emails()
            if normalized not in emails:
                emails.append(normalized)
                save_saved_emails(emails)
    return render_template(
        "index.html",
        rows=None,
        rows_json="[]",
        email=email,
        only_used=False,
        error=None,
        saved_emails=load_saved_emails(),
    )


@app.route("/delete-email", methods=["POST"])
def delete_email():
    email = request.form.get("email", "").strip()
    emails = load_saved_emails()
    emails = [e for e in emails if e != email]
    save_saved_emails(emails)
    return render_template(
        "index.html",
        rows=None,
        rows_json="[]",
        email="",
        only_used=False,
        error=None,
        saved_emails=emails,
    )


@app.route("/download/<fmt>", methods=["POST"])
def download(fmt):
    email = request.form.get("email", "unknown").strip()
    try:
        rows = json.loads(request.form.get("data", "[]"))
    except json.JSONDecodeError:
        rows = []

    found = [r["site"] for r in rows if r.get("status") == "+"]
    notfound = [r["site"] for r in rows if r.get("status") == "-"]
    errored = [r["site"] for r in rows if r.get("status") not in ("+", "-")]

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_email = re.sub(r"[^a-zA-Z0-9]+", "_", email)
    filename = f"holehe_report_{safe_email}_{timestamp}.{fmt}"

    if fmt == "json":
        payload = {
            "email": email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "found": found,
            "not_found": notfound,
            "rate_limited_or_error": errored,
        }
        content = json.dumps(payload, indent=2)
        mimetype = "application/json"
    else:  # txt
        lines = [
            f"Holehe report for: {email}",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            "",
            f"Found ({len(found)}):",
            *([f"  - {s}" for s in found] or ["  (none)"]),
            "",
            f"Not Found ({len(notfound)}):",
            *([f"  - {s}" for s in notfound] or ["  (none)"]),
            "",
            f"Rate Limited / Error ({len(errored)}):",
            *([f"  - {s}" for s in errored] or ["  (none)"]),
        ]
        content = "\n".join(lines)
        mimetype = "text/plain"

    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
