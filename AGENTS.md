# Development Rules

## Conversational Style

- Keep answers short and concise.
- Technical prose only, be direct. No fluff, filler, or emojis in commits, code, or comments.
- Answer user questions first before executing edits or commands.
- State whether you agree or disagree with user feedback before explaining changes.
- Explain non-trivial designs as: problem, concrete trace, then solution.
- **Value-First Decision**: Always explain user and business value in plain, non-technical terms before proposing actions or asking for decisions. Do not dump raw protocol terms without stating what problem it solves and what the user actually gets.

## Code Quality & Architecture

- **CodeGraph-First**: Call `codegraph_explore` before modifying architectural components to inspect callers and blast radius.
- **Node Control Plane**: All node mutations (add, remove, relay, hy2) must pass through `NodeManager` (`server/nodekit/node_manager.py`) with `flock`. Never mutate `nodes.json` directly.
- **Safety Provenance**: Always verify HMAC signature via `provenance.verify_provenance` before restarting or killing remote services. Abort on invalid or missing signature.
- **Ephemeral Credentials**: Never write cloud credentials (`SecretId`/`SecretKey`) or SSH passwords to disk or logs; consume in memory only.
- **RSA 2048 Certificates**: Use `remote_config.generate_self_signed_cert_pem` for universal cross-platform HY2 certificate generation.
- **Gateway Matching**: All admin HTTP routes in `server/admin.py` must support dual prefix matching (`/api/*` and bare paths) for Caddy `handle_path` compatibility.

## Dual-Track Research & Sync

- **Changelog Scope**: Only record user-facing changes, production incident fixes, or test gate upgrades in [`docs/01-变更记录.md`](docs/01-变更记录.md). Never log minor code refactors, typos, or isolated unit tests.
- **ADR Append**: Append a new entry to [`research/04-adr-decisions.md`](research/04-adr-decisions.md) whenever an architectural trade-off or system-wide invariant changes (never rewrite existing records).
- **Atomic Commits**: Update [`research/05-interface-contracts.md`](research/05-interface-contracts.md) in the exact same commit whenever an API payload, return structure, or deployment flag changes.
- **Honest Status**: Mark unimplemented specifications as `[STATUS: PROPOSED]`, and completed implementations as `[STATUS: IMPLEMENTED]`.

## Git & Delivery

- Stage explicit files (`git add <file1> <file2>`); never use `git add .` or `git add -A`.
- Conventional commit message format: `{feat,fix,docs,refactor}[(scope)]: <concise description>`.
- Never run destructive git commands: `git reset --hard`, `git clean -fd`, `git commit --no-verify`.
- Before marking any task complete, verify that `./scripts/test.sh` passes 100% (538+ checks green), auto-update matching docs above, then commit and push.

## User Override

If the user's explicit instructions conflict with any rule here, request confirmation before overriding, then execute as instructed.
