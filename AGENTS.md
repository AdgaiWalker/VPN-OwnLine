# Development Rules

## Conversational Style

- Keep answers short and concise.
- Technical prose only, be direct. No fluff, filler, or emojis in commits, code, or comments.
- Answer user questions first before executing edits or commands.
- State whether you agree or disagree with user feedback before explaining changes.
- Explain non-trivial designs as: problem, concrete trace, then solution.
- **Value-First Decision**: Always explain user and business value in plain, non-technical terms before proposing actions or asking for decisions. Do not dump raw protocol terms without stating what problem it solves and what the user actually gets.
- **Outcome-First Delivery**: On task completion, report only user/business value, test/deployment status, and next actionable steps. Never dump raw execution logs or procedural noise.

## Four-State Asset Lifecycle

- **Release (运行态)**: Root-level single source of truth for runtime execution (`server/`, `web/`, `deploy/`, `scripts/`, `tests/`). Never clutter root with scratch prototypes or operational dumps.
- **Working (演进态)**: Active architecture, specification, and research artifacts (`docs/`, `research/`).
- **Archive (归档态)**: Retired prototypes, historical specifications, superseded code (`archive/prototypes/`, `archive/historical-specs/`).
- **Private (私有态)**: Host keys, credentials, local emergency tarballs (`.ops-private/`, `.backups-private/`). Never commit to Git (must be `.gitignore` protected).

## Code Quality & Architecture

- **CodeGraph-First**: Call `codegraph_explore` before modifying architectural components to inspect callers and blast radius.
- **Modular Web Pipeline**: Edit frontend code exclusively in `web/src/{css,html,js}` and synthesize via `scripts/build_web.py`. Never edit `web/index.html` directly.
- **Inspection & Deletion Guard**: Read files in full before wide-ranging edits; never rely on partial search snippets. Always confirm before removing code or functionality that appears intentional.
- **Node Control Plane**: All node mutations (add, remove, relay, hy2) must pass through `NodeManager` (`server/nodekit/node_manager.py`) with `flock`. Never mutate `nodes.json` directly.
- **Safety Provenance**: Always verify HMAC signature via `provenance.verify_provenance` before restarting or killing remote services. Abort on invalid or missing signature.
- **Ephemeral Credentials**: Never write cloud credentials (`SecretId`/`SecretKey`) or SSH passwords to disk or logs; consume in memory only.
- **RSA 2048 Certificates**: Use `remote_config.generate_self_signed_cert_pem` for universal cross-platform HY2 certificate generation.
- **Gateway Matching**: All admin HTTP routes in `server/admin.py` must support dual prefix matching (`/api/*` and bare paths) for Caddy `handle_path` compatibility.

## Three-Tier Document Synchronization

- **L0 (Micro / Implementation)**: Minor internal refactors, isolated unit tests, or code cleanup require zero document changes; code is the executable truth.
- **L1 (Release / User-Facing)**: User-facing features, UX improvements, incident fixes, or test gate threshold changes must append to [`docs/01-变更记录.md`](docs/01-变更记录.md) and update badges in [`README.md`](README.md).
- **L2 (Architecture / Invariant)**: System topology, protocol contracts, network invariants, API payloads, or deployment flags must atomically append a new ADR in [`research/04-adr-decisions.md`](research/04-adr-decisions.md) (never rewrite existing records) and update [`research/05-interface-contracts.md`](research/05-interface-contracts.md) in the exact same commit. Mark unimplemented as `[STATUS: PROPOSED]`, completed as `[STATUS: IMPLEMENTED]`.

## Git & Delivery

- Stage explicit files (`git add <file1> <file2>`); never use `git add .` or `git add -A`.
- Conventional commit message format: `{feat,fix,docs,refactor}[(scope)]: <concise description>`.
- Never run destructive git commands: `git reset --hard`, `git clean -fd`, `git commit --no-verify`.
- **Offline Tests & Regression Guards**: Tests must run 100% offline with zero paid token or external network dependencies (use mocks). Every bug fix must include a regression test.
- **Autonomous Turnkey DoD**: On receiving a user intent, execute the full lifecycle autonomously (code, build, test, deploy, doc sync, commit, push). Never pause for micro-confirmations on standard engineering steps. Ensure `./scripts/test.sh` passes 100% (541+ checks green) before delivery.

## User Override

If the user's explicit instructions conflict with any rule here, request confirmation before overriding, then execute as instructed.
