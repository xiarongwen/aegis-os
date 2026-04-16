# AEGIS (Agent Evolution & Governance via Git Integration System)

> Git-Native Multi-Agent Operating System for Enterprise AI Development  
> Version: 1.2.0  
> Runtime: Host-native AEGIS Bot on Claude Code CLI

## Core Philosophy

1. **Git is the OS**: Workflow state, review evidence, and evolution history live in Git.
2. **Registry is the source of truth**: `.aegis/core/registry.json` defines every agent; `agents/*/agent.json` are derived artifacts.
3. **Control Plane Enforces the Rules**: `python3 -m tools.control_plane` validates config, metadata, contracts, hooks, and evolution.
4. **Host Session Is The Orchestrator**: The primary AEGIS entry is the current Claude/Codex session via `/aegis`, not an external wrapper CLI.
5. **Strict Gated Flow**: L1 → L2 → L3 → L4 → L5, with independent gate reviewers.
6. **Review Is A Loop**: Gates close through `review -> fix -> re-review -> ... -> LGTM`, not a one-shot checkbox.
7. **Requirement Locking**: Planning emits a frozen `requirements-lock.json`; every stage from L3 onward must match its hash and QA must produce traceability evidence.
8. **DRY-First Parallel Development**: L3 requires `task_breakdown.json`, `implementation-contracts.json`, owned write scopes, and per-agent `reuse-audit.json` before development is considered valid.
9. **Host Capability Enhancement**: Agents may enhance themselves with host-native skills/tools only through abstract contracts plus `shared-contexts/host-capability-map.yml`.
10. **Conservative Evolution**: Nightly evolution only keeps changes that improve score and still pass doctor.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `bash scripts/bootstrap.sh` | Validate control plane, sync metadata, sync skills, and install cron |
| `/aegis ...` | Primary host-native AEGIS entry inside Claude Code |
| `python3 -m tools.control_plane doctor` | Run full control-plane self-check |
| `python3 -m tools.automation_runner bootstrap "..."` | Bootstrap a workflow for the host-native orchestrator or fallback flows |
| `python3 -m tools.control_plane sync-agent-metadata` | Regenerate derived `agents/*/agent.json` |
| `python3 -m tools.control_plane workflow-dry-run` | Simulate the legal workflow path |
| `python3 -m tools.control_plane write-state --workflow <id> --state <STATE>` | Advance state only through legal control-plane transitions |
| `bash .aegis/hooks/pre-agent-run.sh <agent> <workflow>` | Validate runtime preconditions |
| `bash .aegis/hooks/post-agent-run.sh <agent> <workflow>` | Validate outputs and commit workflow artifacts |
| `bash .aegis/schedules/nightly-evolution.sh` | Run conservative nightly agent evolution |

## Workflow States

`INIT → L1_RESEARCH → L1_REVIEW → L2_PLANNING → L2_REVIEW → L3_DEVELOP → L3_CODE_REVIEW → L3_SECURITY_AUDIT → L4_VALIDATE → L4_REVIEW → L5_DEPLOY → L5_REVIEW → DONE`

If a gate exceeds retry policy or a blocking security finding is detected, the workflow moves to `BLOCKED`.

## Control-Plane Guarantees

- Standard-machine-readable config in `.aegis/core/orchestrator.yml`
- Registry schema validation through `.aegis/core/registry.schema.json`
- Tool contract validation through `shared-contexts/tool-contracts.yml`
- Host capability binding validation through `shared-contexts/host-capability-map.yml`
- Requirement-lock schema validation and drift protection from L3 onward
- Task-breakdown, implementation-contract, and reuse-audit validation for L3 execution
- Derived metadata parity between registry and every `agents/*/agent.json`
- Independent reviewer validation for every gate
- Review-loop artifact validation for `review-loop-status.json`, `review-round-N.md`, and `review-passed.json`
- State transitions enforced through control-plane `write-state`
- Locked-requirement hash validation before development, QA, and deployment

## Host-Native Entry

AEGIS should be used as a host-native bot:

- In Claude Code, trigger AEGIS through `/aegis ...`
- The current host session becomes the orchestrator
- `tools/automation_runner` is fallback/debug infrastructure, not the primary UX

See [docs/AEGIS-host-native-architecture-v1.md](/Users/it/aegis-os/docs/AEGIS-host-native-architecture-v1.md).

## Evolution

Every night at 02:00, `.aegis/schedules/nightly-evolution.sh` runs the control-plane evolution command.

- Evolution creates an isolated git worktree
- Each evolvable agent is scored against the shared rubric
- Deterministic low-risk improvements are attempted
- Candidates are kept only if the score improves and `doctor` still passes
- Every result is written to `.aegis/core/evolution.log`

## Review Loop

Every gated review now closes through:

`review -> fix -> re-review -> ... -> LGTM`

Control-plane enforcement:

- Reviewers must emit `review-loop-status.json` and `review-round-N.md`
- `review-passed.json` is valid only when the verdict is `LGTM`
- Fixing agents must answer findings in `fix-response-round-N.md`
- The orchestrator may only advance using `next_state_hint` plus `write-state`

See [docs/requirements/review-fix-loop.md](/Users/it/aegis-os/docs/requirements/review-fix-loop.md).

## Recovery

To recover the system on another machine:

```bash
git clone <your-repo> ~/aegis-os
cd ~/aegis-os
bash scripts/bootstrap.sh
```
