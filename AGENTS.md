# Development Rules

## Conversational Style

- Keep answers short and concise. Technical prose only; zero emojis in commits, code, docs, or comments.
- Answer user questions first; state agree/disagree with user feedback before explaining changes.
- Explain non-trivial designs as problem -> trace -> solution.
- **Value-First Decision / Outcome-First Delivery**: Explain user/business value before proposing changes; report only value, verification status, and next steps on completion.

## Single Docs Root & Boundaries

- **Single Docs Root (`docs/`)**: Active non-code files live only in `docs/` (`adr.md`, `backlog.md`, `plans/`, `01-变更记录.md`, `02-本地诊断事件表.md`, `server-buying-guide.md`) plus root `AGENTS.md`, `README.md`, `GLOSSARY.md`. Retired assets live in permanent Git tags (e.g. `archive/pre-cleanup-20261123`), never in `HEAD`. Runtime secrets stay in `.ops-private/` and `.backups-private/` (`.gitignore` protected).
- **CodeGraph vs Docs Seam Boundary**: Query Python/JS call graphs live via `codegraph_explore` (run `codegraph sync -q` after edits). CodeGraph cannot trace these 3 seams, pinned here and enforced by tests:
  1. Dual HTTP prefix (`/api/*` and bare) between `web/src/js` and `server/admin.py` (Caddy `handle_path`);
  2. Host/Shell/systemd invariants: `/etc/caddy/Caddyfile` (`0640 root:caddy`, no `:80`, `handle_errors { header -Server }`), `settings.json` (`0600` + `AtomicJsonStore` lock), `/opt/sing-box/{config.json,hy2.key}` (`0640 root:sing-box`), `sing-box.service` (`ConditionPathExists=!/var/lib/ownline/quota-paused`), `cf_origin_lock.sh` never touches `22`/`443`;
  3. Build pipeline: `web/src/data/onboarding.json` + `web/src/{css,html,js}` -> `scripts/build_web.py --check`.
- **Doc Sync**: L0 minor/test edits require 0 doc changes. L1 releases append to [`docs/01-变更记录.md`](docs/01-变更记录.md) and update [`README.md`](README.md). L2 causal architecture changes append to [`docs/adr.md`](docs/adr.md) (updating its top Active Index) and track open items in [`docs/backlog.md`](docs/backlog.md). Plans in `docs/plans/` must be `YYYY-MM-DD-<topic>.md` with `Status: ACTIVE|PARTIAL` and leave `HEAD` once closed.

## Architecture, Security & UX Redlines

- **CodeGraph-First & Safe Edits**: Run `codegraph_explore` before changing core modules; read target files before wide edits; confirm before deleting intentional code.
- **Modular Web Pipeline**: Edit frontend only in `web/src/{css,html,js}` and `web/src/data/onboarding.json`; synthesize via `scripts/build_web.py`.
- **Control Plane & Provenance**: All node mutations pass through `NodeManager` (`server/nodekit/node_manager.py`) with `flock`; verify HMAC via `provenance.verify_provenance` before service restarts/kills.
- **Credentials & Crypto**: Never write `SecretId`/`SecretKey` or SSH passwords to disk/logs; consume in memory only. Use `remote_config.generate_self_signed_cert_pem` (RSA 2048) for HY2.
- **Ethical & Confirmation Redlines**: Never modify OS timezone, browser language, fonts, or `Intl` locale to spoof overseas identity. Always confirm explicitly with the user before deleting any node, resetting a server password, or reinstalling a cloud host OS.
- **0-5 UX Principles**: Follow Occam's razor ("如无必要，勿增实体"); diverge then converge; 0 self-reflection; 1 automate & register events in `local_diag.py` ([`docs/02-本地诊断事件表.md`](docs/02-本地诊断事件表.md)); 2 progressive disclosure & graceful fallback UI; 3 spread attention; 4 3-second blind scan & zero emojis; 5 reserve logs/update/fallback UI upfront.

## Git & Verification

- Stage explicit files (`git add <files>`); never `git add .`, `git add -A`, `git reset --hard`, `git clean -fd`, or `git commit --no-verify`. Conventional commits: `{feat,fix,docs,refactor}[(scope)]: <desc>`.
- Offline tests only (mocks, regression guard for every bug fix). Execute full turnkey DoD autonomously and ensure `./scripts/test.sh` passes 100% before delivery.
- **User Override**: If explicit user instructions conflict with any rule here, confirm before overriding, then execute as instructed.
