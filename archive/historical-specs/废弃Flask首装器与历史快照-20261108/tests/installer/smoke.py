"""Opt-in destructive smoke test, restricted to a disposable ownline-smoke-* Docker fixture.
No real server credentials are accepted. SSH passwords/keys remain in this process memory.
Usage: .venv/bin/python tests/installer/smoke.py ownline-smoke-20261101
"""

import base64
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

import paramiko
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server.installer.transport import fingerprint  # noqa: E402

NAME = sys.argv[1] if len(sys.argv) > 1 else ""
if not NAME.startswith("ownline-smoke-") or "/" in NAME:
    raise SystemExit("Only a disposable ownline-smoke-* Docker fixture is accepted")
DATA = ROOT / ".installer-local" / NAME
DATA.mkdir(mode=0o700, exist_ok=True)
API_PORT = int(os.environ.get("OWNLINE_SMOKE_API_PORT", "4180"))
SSH_PORT = int(os.environ.get("OWNLINE_SMOKE_SSH_PORT", "18422"))
HTTPS_PORT = int(os.environ.get("OWNLINE_SMOKE_HTTPS_PORT", "18443"))
BREAK_APT = os.environ.get("OWNLINE_SMOKE_BREAK_APT") == "1"
API = "http://127.0.0.1:" + str(API_PORT)
# Public, disposable localhost-only UI test login; never used for a real server.
AUTH = base64.b64encode(b"admin:OwnLine-local-test-only").decode()
csrf = ""
passed = []


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    passed.append(label)
    print("PASS " + label, flush=True)
    (DATA / "smoke-progress.json").write_text(
        json.dumps({"passed": passed}, ensure_ascii=False, indent=2)
    )


def docker(*args, data=None, required=True):
    p = subprocess.run(
        ["docker", "exec", *(["-i"] if data is not None else []), NAME, *args],
        input=data,
        capture_output=True,
    )
    if required and p.returncode:
        raise RuntimeError("Disposable fixture command failed: " + args[0])
    return p


def api(path, body=None, key=None, expected=200):
    headers = {"Authorization": "Basic " + AUTH}
    if body is not None:
        headers.update(
            {"Origin": API, "Content-Type": "application/json", "X-CSRF-Token": csrf}
        )
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(
        API + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code = r.status
            value = json.load(r)
    except urllib.error.HTTPError as e:
        code = e.code
        value = json.load(e)
    if code != expected:
        raise AssertionError(
            "API " + path + " status=" + str(code) + " code=" + str(value.get("code"))
        )
    return value


def launch(command):
    out = open(DATA / (command + ".log"), "ab", buffering=0)
    return subprocess.Popen(
        [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "server.installer",
            command,
            "--config",
            str(DATA / "config.json"),
            "--port",
            str(API_PORT),
        ],
        cwd=ROOT,
        stdout=out,
        stderr=out,
    )


def wait_job(jid, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = api("/api/jobs/" + jid)
        if job["state"] in (
            "succeeded",
            "failed",
            "needs_attention",
            "awaiting_credentials",
        ):
            return job
        time.sleep(0.3)
    raise TimeoutError("job did not reach a reviewable state")


def snapshot():
    # Checks provisioning paths and service state; SSH's own authentication logs are expected.
    return docker(
        "python3",
        "-c",
        "import json;from pathlib import Path;print(json.dumps({p:Path(p).exists() for p in ['/opt/web','/opt/web-data','/opt/sing-box','/var/lib/ownline-installer','/etc/caddy/Caddyfile']}))",
    ).stdout


password = secrets.token_urlsafe(24)
docker("chpasswd", data=("root:" + password + "\n").encode())
key = paramiko.RSAKey.generate(2048)
pem = io.StringIO()
key.write_private_key(pem)
docker("mkdir", "-p", "/root/.ssh")
docker(
    "sh",
    "-c",
    "cat > /root/.ssh/authorized_keys && chmod 700 /root/.ssh && chmod 600 /root/.ssh/authorized_keys",
    data=(key.get_name() + " " + key.get_base64() + "\n").encode(),
)
hostkey = docker("cat", "/etc/ssh/ssh_host_ed25519_key.pub").stdout.decode().split()
pin = fingerprint(paramiko.Ed25519Key(data=base64.b64decode(hostkey[1])))
base = {
    "host": "127.0.0.1",
    "ssh_port": SSH_PORT,
    "username": "root",
    "fingerprint": pin,
}
config = {
    "origin": API,
    "auth_user": "admin",
    "auth_hash": generate_password_hash("OwnLine-local-test-only"),
    "csrf_key": secrets.token_hex(32),
    "data_dir": str(DATA / "data"),
    "source_dir": str(ROOT),
    "development": True,
    "allowed_targets": ["127.0.0.1"],
    "test_internal_tls": True,
    "verification_url": "https://localhost:" + str(HTTPS_PORT) + "/",
    "tls_ca_file": str(DATA / "fixture-root.crt"),
}
fd = os.open(DATA / "config.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(config, f)
worker = launch("worker")
server = launch("api")
(DATA / "processes.json").write_text(
    json.dumps({"api": server.pid, "worker": worker.pid})
)
for _ in range(50):
    try:
        csrf = api("/api/setup")["csrf_token"]
        break
    except OSError:
        time.sleep(0.2)
else:
    raise RuntimeError("API not available")
before = snapshot()
# Wrong pin is rejected before authentication, then no-pin explicitly asks for confirmation.
wrong = {**base, "fingerprint": "SHA256:" + "A" * 43, "password": password}
jid = api("/api/checks", wrong, expected=202)["job_id"]
job = wait_job(jid)
check("changed host key rejected", job["error_code"] == "HOST_KEY_CHANGED")
jid = api(
    "/api/checks", {**base, "fingerprint": "", "password": password}, expected=202
)["job_id"]
job = wait_job(jid)
check(
    "first host key requires confirmation",
    job["error_code"] == "HOST_KEY_CONFIRMATION"
    and job["result"]["fingerprint"] == pin,
)
jid = api(
    "/api/checks", {**base, "password": "incorrect disposable password"}, expected=202
)["job_id"]
job = wait_job(jid)
check("wrong SSH password rejected", job["error_code"] == "SSH_AUTH_FAILED")
jid = api("/api/checks", {**base, "private_key": pem.getvalue()}, expected=202)[
    "job_id"
]
job = wait_job(jid)
check("real private-key SSH and custom port", job["state"] == "succeeded")
jid = api("/api/checks", {**base, "password": password}, expected=202)["job_id"]
job = wait_job(jid)
check(
    "real password SSH and Debian/systemd inspection",
    job["state"] == "succeeded" and job["result"]["systemd"],
)
check("connection checks leave provisioning paths untouched", snapshot() == before)
body = {"check_job_id": jid, "confirm_install": True, "domain": "localhost"}
idem = secrets.token_hex(16)
install = api("/api/jobs", body, idem, 202)["job_id"]
check(
    "duplicate POST reuses original installation",
    api("/api/jobs", body, idem, 202)["job_id"] == install,
)
busy = api("/api/jobs", body, secrets.token_hex(16), 409)
check(
    "new submission cannot duplicate active target",
    busy["code"] == "TARGET_BUSY" and busy["detail"]["job_id"] == install,
)
# Wait until target independently owns a running task, then terminate the local worker.
for _ in range(240):
    p = docker(
        "test",
        "-f",
        "/var/lib/ownline-installer/jobs/" + install + "/state.json",
        required=False,
    )
    if not p.returncode:
        remote = json.loads(
            docker(
                "cat", "/var/lib/ownline-installer/jobs/" + install + "/state.json"
            ).stdout
        )
        if remote["state"] == "running":
            break
        if remote["state"] == "failed":
            raise AssertionError(
                "remote install failed before interruption test, phase "
                + str(remote["stage"])
            )
    time.sleep(0.5)
else:
    raise TimeoutError("remote task not started")
worker.terminate()
worker.wait(10)
# API restart does not affect the target systemd installation.
server.terminate()
server.wait(10)
server = launch("api")
worker = launch("worker")
(DATA / "processes.json").write_text(
    json.dumps({"api": server.pid, "worker": worker.pid})
)
for _ in range(50):
    try:
        csrf = api("/api/setup")["csrf_token"]
        job = api("/api/jobs/" + install)
        if job["state"] == "awaiting_credentials":
            break
    except OSError:
        pass
    time.sleep(0.2)
check(
    "API/worker restart retains the original task",
    job["id"] == install and job["state"] == "awaiting_credentials",
)
api("/api/jobs/" + install + "/credentials", {"password": password}, expected=202)
# Copy only the disposable local CA's public certificate, never its private key.
for _ in range(900):
    p = docker(
        "cat",
        "/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt",
        required=False,
    )
    if p.returncode == 0 and b"BEGIN CERTIFICATE" in p.stdout:
        (DATA / "fixture-root.crt").write_bytes(p.stdout)
    job = api("/api/jobs/" + install)
    if job["state"] in ("failed", "needs_attention", "awaiting_credentials"):
        break
    time.sleep(1)
if BREAK_APT:
    check(
        "source outage reports dependency failure without reinstallation",
        job["error_code"] == "DEPENDENCY_UNAVAILABLE",
    )
    restore_hosts = """from pathlib import Path
p=Path('/etc/hosts');lines=p.read_text().splitlines()
lines=['163.181.26.190\\tmirrors.aliyun.com' if 'mirrors.aliyun.com' in line else line for line in lines]
p.write_text('\\n'.join(lines)+'\\n')
"""
    docker("python3", "-c", restore_hosts)
    api("/api/jobs/" + install + "/credentials", {"password": password}, expected=202)
    for _ in range(360):
        remote = json.loads(
            docker(
                "cat", "/var/lib/ownline-installer/jobs/" + install + "/state.json"
            ).stdout
        )
        if remote.get("attempt") == 1 and remote["state"] in (
            "starting",
            "running",
            "installed",
        ):
            break
        current = api("/api/jobs/" + install)
        if current["state"] == "needs_attention":
            raise AssertionError("resume failed: " + str(current["error_code"]))
        time.sleep(0.5)
    check(
        "network recovery resumes the same target task once", remote.get("attempt") == 1
    )
    worker.terminate()
    worker.wait(10)
    worker = launch("worker")
    (DATA / "processes.json").write_text(
        json.dumps({"api": server.pid, "worker": worker.pid})
    )
    for _ in range(60):
        job = api("/api/jobs/" + install)
        if job["state"] in ("awaiting_credentials", "needs_attention", "succeeded"):
            break
        time.sleep(0.2)
    api("/api/jobs/" + install + "/credentials", {"password": password}, expected=202)
    for _ in range(900):
        p = docker(
            "cat",
            "/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt",
            required=False,
        )
        if p.returncode == 0 and b"BEGIN CERTIFICATE" in p.stdout:
            (DATA / "fixture-root.crt").write_bytes(p.stdout)
        job = api("/api/jobs/" + install)
        if job["state"] in ("failed", "needs_attention", "awaiting_credentials"):
            break
        time.sleep(1)
check(
    "lost delivery password requires explicit consent",
    job["error_code"] == "DELIVERY_CONFIRMATION",
)
api(
    "/api/jobs/" + install + "/credentials",
    {"password": password, "reset_delivery_password": True},
    expected=202,
)
job = wait_job(install, 150)
check(
    "HTTPS authentication and real subscription verified",
    job["state"] == "succeeded" and job["result"]["node_count"] == 2,
)
check(
    "verified installation cache is cleaned",
    job["result"]["installation_cache_cleaned"]
    and docker(
        "test",
        "-e",
        "/var/lib/ownline-installer/jobs/" + install + "/source/packages",
        required=False,
    ).returncode
    != 0,
)
delivery = api("/api/jobs/" + install + "/delivery")
check(
    "verified delivery contains generated login and subscription",
    bool(delivery["password"]) and "/s/" in delivery["subscription_url"],
)
remote = json.loads(
    docker("cat", "/var/lib/ownline-installer/jobs/" + install + "/state.json").stdout
)
check(
    "target installed once with stable task identity",
    remote["state"] == "installed" and remote["job_id"] == install,
)
check(
    "target sing-box is active",
    docker("systemctl", "is-active", "sing-box").stdout.strip() == b"active",
)
# Quota protection acts directly on the target, outside the installation queue.
from server.nodekit import quota_guard  # noqa: E402

node = {"host": "127.0.0.1", "local": True, "name": "disposable-fixture"}


def quota_runner(cmd, **kwargs):
    p = docker("bash", "-c", cmd[-1], required=False)
    return subprocess.CompletedProcess(cmd, p.returncode)


state_file = str(DATA / "quota-state.json")
actions = quota_guard.enforce_quota(
    [node],
    {"127.0.0.1": {"used": 90, "total": 100}},
    runner=quota_runner,
    state_file=state_file,
)
check(
    "85 percent protection stops the real proxy independently",
    actions[0]["action"] == "stop"
    and docker("systemctl", "is-active", "sing-box", required=False).stdout.strip()
    == b"inactive",
)
blocked = docker(
    "bash",
    "-c",
    "flock -x -w 5 /run/ownline-service.lock sh -c 'test ! -e /var/lib/ownline/quota-paused && systemctl start sing-box'",
    required=False,
)
check("installer cannot restart a quota-protected proxy", blocked.returncode != 0)
quota_guard.enforce_quota([node], {}, runner=quota_runner, state_file=state_file)
check(
    "unknown usage does not remove protection",
    docker("test", "-f", "/var/lib/ownline/quota-paused", required=False).returncode
    == 0,
)
actions = quota_guard.enforce_quota(
    [node],
    {"127.0.0.1": {"used": 0, "total": 100}},
    runner=quota_runner,
    state_file=state_file,
)
check(
    "known recovered quota resumes proxy and clears marker",
    actions[0]["action"] == "start"
    and docker("test", "-e", "/var/lib/ownline/quota-paused", required=False).returncode
    != 0,
)
# Controller persistence contains no temporary or delivery credentials, raw node data or subscription token.
raw = (DATA / "data/tasks.sqlite3").read_bytes()
check(
    "SQLite never stores SSH secrets or delivery password",
    all(
        v.encode() not in raw
        for v in (
            password,
            pem.getvalue(),
            delivery["password"],
            delivery["subscription_url"].split("/s/")[1].split("/")[0],
        )
    ),
)
check(
    "public job response excludes credential references",
    all(
        v not in json.dumps(job) for v in ("credential_ref", "private_key", "sub_token")
    ),
)
(DATA / "smoke-result.json").write_text(
    json.dumps(
        {
            "scope": "disposable Docker Debian12 arm64, explicit local CA; not public/cloud/device acceptance",
            "passed": passed,
            "job_id": install,
            "management_url": delivery["management_url"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
print(
    "COMPLETE "
    + str(len(passed))
    + " assertions; local API and worker left running for browser QA",
    flush=True,
)
