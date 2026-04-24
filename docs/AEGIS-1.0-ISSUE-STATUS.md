# AEGIS 1.0 Issue Status

Updated: 2026-04-22

This document reconciles the old P0/P1 risk table against the current AEGIS 1.0 implementation. The old table is no longer accurate as a raw "not started" list; several issues are solved in the 1.0 mainline, while a few remain partial and should drive the next development slice.

Status legend:

- Done: implemented and covered by 1.0 behavior/tests.
- Partial: usable baseline exists, but the product contract is not yet strong enough for 1.0 final.
- Obsolete: the issue belonged to the old v1/v2 control-plane path and is not part of the new 1.0 mainline.
- Open: still needs implementation.

## P0 Core Correctness

| ID | Issue | Current 1.0 Status | Evidence | Remaining Work |
| --- | --- | --- | --- | --- |
| P0-1 | Agent runtime trust: router, plan, and executor must agree on the selected local agent CLI/runtime; explicit `--agents codex` or `--agents claude` must not be silently replaced. | Partial | `RunPlanner` passes explicit agent runtime selections into the compatibility `ModelResolver`; unknown explicit selections fail instead of being replaced. Runtime executes `PlanStep.model` directly, where `model` is currently the compatibility field for agent runtime identity. | Make explicit agent/runtime assignment role-aware instead of "first valid runtime for every role"; add stronger pair/swarm/pipeline consistency tests and clear errors when an explicit runtime cannot serve a required role. |
| P0-2 | Input validation: empty, vague, and overlong input must not create a valid session. | Done | `IntentRouter.validate` rejects empty, ambiguous, and too-long requests before session creation. | Keep expanding vague-input examples as product language stabilizes. |
| P0-3 | CLI contract and docs drift: docs mention commands/options that CLI does not support. | Partial | README and Quickstart now describe the 1.0 command surface; legacy v1/v2 commands are separated behind `aegis v2` / `aegis ctl`. | Either implement or explicitly remove remaining aspirational knobs such as `--budget` and `config set`; keep PRD command list aligned with actual parser. |
| P0-4 | Scheduler stability: pair termination, swarm splitting, pipeline context passing, MoA aggregation, dependency-aware fan-out/fan-in. | Partial | Pair has a bounded review/fix loop; pipeline has the eight-stage flow plus verification and done gate; policy blocks fake completion. `RunStep` now carries `depends_on/group/attempt`, swarm and MoA plans express fan-out/fan-in, and the engine executes via a dependency-aware ready queue with durable scheduler events. | Add safe parallel worker execution, richer aggregation prompts, structured retry events, and checkpoint resume from failed stages. |
| P0-5 | Runtime error UX: no bare exit codes; provide structured errors, fallback/retry, and install/config guidance. | Partial | Runtime errors now include command log paths and install/simulate hints for missing CLIs. | Introduce structured runtime error codes, retry/fallback policy, actionable remediation output, and better live display of stdout/stderr. |

## P1 Product Completeness

| ID | Issue | Current 1.0 Status | Evidence | Remaining Work |
| --- | --- | --- | --- | --- |
| P1-1 | Session recovery: checkpoint can record but cannot resume/retry from checkpoint. | Partial | `session resume` / `session recover` exist and replay the original request with source metadata. | Implement checkpoint-level resume, retry-from-stage, and artifact/context reuse. |
| P1-2 | Cost controller: no budget flag, threshold warnings, over-budget stop, or downgrade. | Open | `cost report` exists, but it is reporting-only. | Add `--budget`, config budget consumption, 50/80/100 percent events, stop/downgrade behavior, and tests. |
| P1-3 | Runtime health false negatives: installed agent CLIs marked unavailable due to hard API env dependency. | Done | `agents test` and compatibility `models test` check Codex CLI and Claude Code binaries instead of requiring API env for CLI runtimes. | Add optional deeper auth checks later, but keep binary availability separate from account/API status. |
| P1-4 | Session dirty state: completed session still has `execution_state=executing`. | Done | The 1.0 session schema uses `RunStatus` and does not carry the old v2 `execution_state` field. Completion updates status explicitly. | None for 1.0 mainline. |
| P1-5 | Fake config fields: config contains fields with no real consumer. | Partial | 1.0 config is slimmer than v2 and verification commands are consumed. | Wire `runtime.timeout_seconds`, `runtime.bridge`, and `cost.per_task_budget` into CLI/engine behavior or remove them from defaults. |
| P1-6 | README/product docs still centered on old Workflow/Team Pack/Governance story. | Done | README and `AEGIS-1.0-QUICKSTART.md` now present the 1.0 collaboration cockpit and command surface first. | Keep old architecture docs clearly marked as legacy/reference. |
| P1-7 | Visual interface: old `aegis ui` control-plane TUI, no 1.0 collaboration view. | Done for 1.0 | `aegis ulw --live` uses the 1.0 cockpit with progress, stages, live events, council/review/verification blocks, and text fallback. | Decide separately whether to keep or delete old `aegis ui`; do not make it the 1.0 primary UI. |

## Next Development Order

1. Close P0-1 fully: role-aware explicit agent runtime validation and stronger consistency tests.
2. Close P0-5 fully: structured runtime errors plus retry/fallback policy.
3. Close P0-4 enough for 1.0: dependency-aware scheduler, better swarm/MoA decomposition, aggregation, and retry semantics.
4. Close P1-2: real budget controller, thresholds, and stop/downgrade events.
5. Close P1-1: checkpoint-level resume/retry after the run artifacts are stable.
