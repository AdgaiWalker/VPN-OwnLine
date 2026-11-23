---
name: ownline-local
description: Orchestrate Evergreen OwnLine across macOS, Windows, and Linux using the cross-platform `ownline.py` local engine, blind credential vault, pluggable capabilities, and declarative topology apply without exposing plaintext secrets.
---

# Evergreen OwnLine Local Agent Skill

## Hard Safety Invariant

1. **Zero Plaintext Secrets in Chat or Shell History**: Never ask the user to paste SSH passwords, private keys, Tencent `SecretKey`, Webshare proxy credentials, or panel passwords into chat, CLI flags, or JSON files.
2. **Always Use Blind Vault Handles**: Acquire every secret exclusively through `python3 ownline.py vault request --slot <slot> --json` (`ssh`, `tencent_api`, `webshare_isp`, `panel_auth`). Desktop hosts auto-open the `127.0.0.1/vault?req=...` card; headless terminals automatically fall back to masked `getpass`. You receive only an opaque handle (`vh_...`) and redacted summary.
3. **Never Guess Unverified Claims**: Rely strictly on JSON output from `ownline.py`. On fingerprint mismatch (`code == "HOST_KEY_CONFIRMATION"`), show the fingerprint to the user for verification before re-running with `--fingerprint`.

## Standard End-to-End Lifecycle

### 0. Zero-to-One Resource Lookup & Intent Mapping
1. Map the user's goal deterministically to a topology blueprint before prompting for credentials:
```bash
python3 ownline.py plan --intent "<user_goal>" --json
```
Built-in presets (`python3 ownline.py plan --list --json`):
- `budget_basic`: Single overseas node (Reality + HY2), slots `ssh`, `panel_auth`.
- `ai_clean_ip`: Overseas node + Webshare static residential ISP, slots `ssh`, `panel_auth`, `webshare_isp`.
- `peak_stable`: Overseas landing + domestic relay for peak congestion, slots `ssh`, `panel_auth` (+ `relay.method = reverse_join`).
- `full_stack`: Domestic relay + overseas landing + Webshare residential ISP, slots `ssh`, `panel_auth`, `webshare_isp`.
2. Read [web/src/data/onboarding.json](../../web/src/data/onboarding.json) before recommending any VPS provider, port rule, domestic relay, Webshare static residential proxy, client download, Apple ID path, or optional custom domain. Do not invent prices or third-party links; cite only the official URLs, historical price ranges, and `checked_at` date recorded in that file. (On Windows, invoke `py -3 ownline.py` or `python ownline.py` instead of `python3`.)

### 1. Preflight
```bash
python3 ownline.py doctor --json
```
Verify `ok == true` before touching remote servers.

### 2. Acquire SSH Handle & Install Master Server
```bash
python3 ownline.py vault request --slot ssh --hint <server_ip> --json
python3 ownline.py check --vault-handle <vh_ssh> --json
# If exit code 2 (HOST_KEY_CONFIRMATION): verify SHA256 fingerprint with user, then:
python3 ownline.py check --vault-handle <vh_ssh> --fingerprint <SHA256:...> --json
python3 ownline.py install --check-token <tok> --confirm --json
python3 ownline.py status --json
```
Wait until `state == "done"`. During the same daemon session, initial panel delivery credentials stay inside daemon memory for seamless handoff to step 3 without exposing the temporary password.

### 3. Discover Capabilities & Apply Full Topology Declaratively
Inspect active capabilities:
```bash
python3 ownline.py cap list --json
```

Collect blind handles for user-chosen panel password and optional Webshare static residential proxy:
```bash
python3 ownline.py vault request --slot panel_auth --label "新面板登录密码" --hint <dashboard_url> --json
python3 ownline.py vault request --slot webshare_isp --label "Webshare 静态住宅出口" --json
```

Preview with `--dry-run` first, then apply:
```bash
python3 ownline.py apply --dry-run --json --plan-json '{
  "rotate_initial_password": {"new_panel_handle": "<vh_new_panel>"},
  "residential_isp": {"isp_handle": "<vh_isp>"},
  "relay": {"method": "reverse_join", "role": "relay", "name": "国内中继-01"},
  "verify": {"quick": false, "check_subscription": true}
}'
```
Remove `--dry-run` after confirming the plan preview.
- `rotate_initial_password` rotates the temporary install password and automatically chains the fresh `active_panel_handle` to `residential-isp`, `relay-expand`, and `topology-verify`.
- `relay` supports `reverse_join` (returns one-time `curl | bash` join command), `ssh_managed` (automated SSH check + install + auto-pair with `ssh_handle`), or `pair_only`.

### 4. Cleanup & Fallback
Clear memory handles after delivery verification:
```bash
python3 ownline.py vault clear --json
```
Inspect redacted local diagnostics if needed:
```bash
python3 ownline.py logs --limit 30 --json
```
If headless input fails, Agent orchestration stalls, or the user prefers a visual UI, hand off silently to the local loopback fallback UI via `python3 ownline.py ui` (`启动安装.command` on macOS, `启动安装.bat` on Windows).
