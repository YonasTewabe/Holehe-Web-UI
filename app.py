import asyncio
import inspect
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from email_validator import EmailNotValidError, validate_email
from flask import Flask, Response, render_template, request, stream_with_context

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Holehe helpers
# ─────────────────────────────────────────────────────────────────────────────

# Matches lines like: [+] Twitter  [-] Adobe  [x] Amazon
LINE_RE = re.compile(r"^\[([+\-x])\]\s+(.*)$")


def check_email(email: str, check_dns: bool = True):
    """Validate email syntax (and optionally MX records). Returns (normalized, error)."""
    try:
        result = validate_email(email, check_deliverability=check_dns)
        return result.normalized, None
    except EmailNotValidError as e:
        return None, f"Invalid email: {e}"


def run_holehe(email: str, only_used: bool = True):
    """Run the holehe CLI and parse its output into structured rows."""
    cmd = ["holehe", email, "-C"]
    if only_used:
        cmd.append("--only-used")

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, cwd=tmpdir
            )
    except subprocess.TimeoutExpired:
        return [], "Lookup timed out. Try again."

    rows = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if "Email used" in line and "Email not used" in line:
            continue
        match = LINE_RE.match(line)
        if match:
            status, site = match.groups()
            site = site.strip()
            if "[" in site or "]" in site:
                continue
            rows.append({"status": status, "site": site})

    error = None
    if result.returncode != 0 and not rows:
        error = result.stderr.strip() or "holehe returned no output."

    return rows, error


# ─────────────────────────────────────────────────────────────────────────────
# User-Scanner helpers
# ─────────────────────────────────────────────────────────────────────────────

def _simple_is_valid_email(email: str) -> bool:
    """Basic email format check used as fallback."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _us_import():
    """Lazy-import user_scanner so the app still starts even if it's not installed."""
    try:
        from user_scanner.core.helpers import (
            ScanConfig,
            load_categories,
            load_modules,
            get_scan_func,
            get_site_name,
            find_category,
            is_loud,
        )
        from user_scanner.core.result import Result, Status

        # is_valid_email was added in a later version — fall back gracefully
        try:
            from user_scanner.core.helpers import is_valid_email
        except ImportError:
            is_valid_email = _simple_is_valid_email

        return dict(
            ScanConfig=ScanConfig,
            is_valid_email=is_valid_email,
            load_categories=load_categories,
            load_modules=load_modules,
            get_scan_func=get_scan_func,
            get_site_name=get_site_name,
            find_category=find_category,
            is_loud=is_loud,
            Result=Result,
            Status=Status,
        )
    except ImportError:
        return None


def _us_available() -> bool:
    return _us_import() is not None


async def _us_scan_all(target: str, is_email: bool, no_nsfw: bool, allow_loud: bool):
    """
    Async generator that yields (Result, done_count, total_count) tuples
    as each module completes.
    """
    us = _us_import()
    if us is None:
        return

    load_categories = us["load_categories"]
    load_modules    = us["load_modules"]
    get_scan_func   = us["get_scan_func"]
    get_site_name   = us["get_site_name"]
    is_loud         = us["is_loud"]
    Result          = us["Result"]
    ScanConfig      = us["ScanConfig"]

    categories = load_categories(is_email=is_email, no_nsfw=no_nsfw)
    all_modules = []
    for cat_name, cat_path in categories.items():
        for module in load_modules(cat_path):
            all_modules.append((cat_name.capitalize(), module))

    sem: asyncio.Semaphore = asyncio.Semaphore(40)
    queue: asyncio.Queue = asyncio.Queue()

    async def worker(cat_name: str, module):
        async with sem:
            site_name = get_site_name(module)
            func = get_scan_func(module)
            params = {
                "site_name": site_name.capitalize(),
                "username": target,
                "category": cat_name,
                "is_email": is_email,
            }
            if not func:
                await queue.put(Result.error(f"{site_name} has no validate_ function", **params))
                return
            if not allow_loud and is_loud(site_name, is_email=is_email):
                await queue.put(Result.skipped().update(**params))
                return
            try:
                if inspect.iscoroutinefunction(func):
                    result = await func(target)
                else:
                    result = await asyncio.to_thread(func, target)
            except Exception as e:
                result = Result.error(e)
            result.update(**params)
            await queue.put(result)

    tasks = [asyncio.create_task(worker(cat, mod)) for cat, mod in all_modules]
    total = len(tasks)
    done  = 0

    while done < total:
        result = await queue.get()
        done  += 1
        yield result, done, total

    await asyncio.gather(*tasks, return_exceptions=True)


def _us_result_to_dict(r) -> dict:
    return {
        "status":      r.status.to_label(r.is_email),
        "status_code": r.status.value,   # 0=found/registered 1=not found 2=error 3=skipped
        "site_name":   r.site_name or "",
        "category":    r.category  or "",
        "url":         r.url       or "",
        "reason":      r.get_reason(),
        "extra":       r.extra,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Holehe
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    return render_template(
        "index.html",
        us_available=_us_available(),
    )


@app.route("/holehe/scan")
def holehe_scan():
    """
    SSE stream endpoint for holehe.
    Query params:
      email      – email address to scan
      only_used  – '1' to return only accounts found
    """
    email     = request.args.get("email", "").strip()
    only_used = request.args.get("only_used", "0") == "1"

    def _err(msg):
        def gen():
            yield "data: " + json.dumps({"type": "error", "message": msg}) + "\n\n"
        return Response(stream_with_context(gen()), mimetype="text/event-stream")

    if not email:
        return _err("Please enter an email address.")

    normalized, validation_error = check_email(email)
    if validation_error:
        return _err(validation_error)

    @stream_with_context
    def generate():
        yield "data: " + json.dumps({"type": "start", "email": normalized}) + "\n\n"

        cmd = ["holehe", normalized, "-C"]
        if only_used:
            cmd.append("--only-used")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=tmpdir,
                )
                rows = []
                for raw_line in proc.stdout:
                    line = raw_line.strip()
                    if not line:
                        continue
                    if "Email used" in line and "Email not used" in line:
                        continue
                    match = LINE_RE.match(line)
                    if not match:
                        continue
                    status, site = match.groups()
                    site = site.strip()
                    if "[" in site or "]" in site:
                        continue
                    row = {"status": status, "site": site}
                    rows.append(row)
                    yield "data: " + json.dumps({"type": "result", "row": row}) + "\n\n"

                proc.wait(timeout=5)

                if proc.returncode != 0 and not rows:
                    stderr = proc.stderr.read().strip()
                    yield "data: " + json.dumps({"type": "error", "message": stderr or "holehe returned no output."}) + "\n\n"
                    return

        except subprocess.TimeoutExpired:
            proc.kill()
            yield "data: " + json.dumps({"type": "error", "message": "Lookup timed out."}) + "\n\n"
            return

        yield "data: " + json.dumps({"type": "done", "email": normalized, "only_used": only_used}) + "\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/download/<fmt>", methods=["POST"])
def download(fmt):
    email = request.form.get("email", "unknown").strip()
    scope = request.form.get("scope", "full")
    try:
        rows = json.loads(request.form.get("data", "[]"))
    except json.JSONDecodeError:
        rows = []

    found    = [r["site"] for r in rows if r.get("status") == "+"]
    notfound = [r["site"] for r in rows if r.get("status") == "-"]
    errored  = [r["site"] for r in rows if r.get("status") not in ("+", "-")]
    timestamp  = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_email = re.sub(r"[^a-zA-Z0-9]+", "_", email)
    filename   = f"holehe_report_{safe_email}_{timestamp}.{fmt}"

    if fmt == "json":
        payload = {"email": email, "found": found}
        if scope == "full":
            payload["not_found"]            = notfound
            payload["rate_limited_or_error"] = errored
        content  = json.dumps(payload, indent=2)
        mimetype = "application/json"
    else:  # txt
        lines = [f"Holehe report for: {email}", "", f"Found ({len(found)}):"]
        lines += [f"  - {s}" for s in found] or ["  (none)"]
        if scope == "full":
            lines += ["", f"Not Found ({len(notfound)}):"]
            lines += [f"  - {s}" for s in notfound] or ["  (none)"]
            lines += ["", f"Rate Limited / Error ({len(errored)}):"]
            lines += [f"  - {s}" for s in errored] or ["  (none)"]
        content  = "\n".join(lines)
        mimetype = "text/plain"

    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Routes — User Scanner
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/us")
def us_index():
    """Redirect to the main page with the user-scanner tab pre-selected."""
    from flask import redirect, url_for
    return redirect(url_for("index") + "#us")


@app.route("/us/scan")
def us_scan():
    """
    SSE stream endpoint for user-scanner.
    Query params:
      target      – email address or username
      mode        – 'email' | 'username'
      no_nsfw     – '1' to exclude adult content
      allow_loud  – '1' to include notifying (loud) modules
    """
    if not _us_available():
        def _err():
            yield "data: " + json.dumps({"type": "error", "message": "user-scanner is not installed."}) + "\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    us         = _us_import()
    target     = request.args.get("target", "").strip()
    mode       = request.args.get("mode", "email").strip()
    no_nsfw    = request.args.get("no_nsfw", "0") == "1"
    allow_loud = request.args.get("allow_loud", "0") == "1"
    is_email   = (mode == "email")

    if not target:
        def _err():
            yield "data: " + json.dumps({"type": "error", "message": "Please enter a target."}) + "\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    if is_email and not us["is_valid_email"](target):
        def _err():
            yield "data: " + json.dumps({"type": "error", "message": f"'{target}' is not a valid email address."}) + "\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    @stream_with_context
    def generate():
        yield "data: " + json.dumps({"type": "start", "target": target, "mode": mode}) + "\n\n"

        loop = asyncio.new_event_loop()
        try:
            agen = _us_scan_all(target, is_email, no_nsfw, allow_loud)
            while True:
                try:
                    result, done, total = loop.run_until_complete(agen.__anext__())
                    data = _us_result_to_dict(result)
                    data["type"]  = "result"
                    data["done"]  = done
                    data["total"] = total
                    yield "data: " + json.dumps(data) + "\n\n"
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/us/download/<fmt>", methods=["POST"])
def us_download(fmt):
    target = request.form.get("target", "unknown").strip()
    mode   = request.form.get("mode", "email").strip()
    scope  = request.form.get("scope", "full")
    try:
        rows = json.loads(request.form.get("data", "[]"))
    except json.JSONDecodeError:
        rows = []

    is_email       = (mode == "email")
    found_label    = "Registered" if is_email else "Found"
    notfound_label = "Not Registered" if is_email else "Not Found"

    found    = [r for r in rows if r.get("status") == found_label]
    notfound = [r for r in rows if r.get("status") == notfound_label]
    errored  = [r for r in rows if r.get("status") not in (found_label, notfound_label)]

    export_rows = found if scope == "found" else rows

    timestamp   = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    safe_target = re.sub(r"[^a-zA-Z0-9]+", "_", target)
    filename    = f"us_report_{safe_target}_{timestamp}.{fmt}"

    target_label = "Email" if is_email else "Username"

    if fmt == "json":
        payload = {
            "target": target,
            "mode":   mode,
            "found":  [{"site": r["site_name"], "url": r.get("url", ""), "category": r.get("category", "")} for r in found],
        }
        if scope == "full":
            payload["not_found"] = [r["site_name"] for r in notfound]
            payload["errors"]    = [{"site": r["site_name"], "reason": r.get("reason", "")} for r in errored]
        content  = json.dumps(payload, indent=2)
        mimetype = "application/json"

    elif fmt == "csv":
        def esc(v):
            return '"' + str(v).replace('"', '""') + '"'
        lines = ["site_name,category,status,url,reason"]
        for r in export_rows:
            lines.append(",".join([
                esc(r.get("site_name", "")),
                esc(r.get("category", "")),
                esc(r.get("status", "")),
                esc(r.get("url", "")),
                esc(r.get("reason", "")),
            ]))
        content  = "\n".join(lines)
        mimetype = "text/csv"

    else:  # txt
        lines = [
            f"User Scanner report for {target_label}: {target}",
            f"Scan mode: {mode}",
            "",
            f"Found ({len(found)}):",
        ]
        lines += [f"  [{r.get('category','')}] {r['site_name']}  {r.get('url','')}" for r in found] or ["  (none)"]
        if scope == "full":
            lines += ["", f"Not Found ({len(notfound)}):"]
            lines += [f"  {r['site_name']}" for r in notfound] or ["  (none)"]
            lines += ["", f"Errors / Skipped ({len(errored)}):"]
            lines += [f"  {r['site_name']}: {r.get('reason','')}" for r in errored] or ["  (none)"]
        content  = "\n".join(lines)
        mimetype = "text/plain"

    return Response(
        content,
        mimetype=mimetype,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
