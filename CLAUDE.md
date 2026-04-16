# AEGIS (Agent Evolution & Governance via Git Integration System)

> Git-Native Multi-Agent Operating System for Enterprise AI Development  
> Version: 1.1.0  
> Runtime: AEGIS Control Plane on Claude Code CLI

## Core Philosophy

1. **Git is the OS**: Workflow state, review evidence, and evolution history live in Git.
2. **Registry is the source of truth**: `.aegis/core/registry.json` defines every agent; `agents/*/agent.json` are derived artifacts.
3. **Control Plane Enforces the Rules**: `python3 -m tools.control_plane` validates config, metadata, contracts, hooks, and evolution.
4. **Strict Gated Flow**: L1 → L2 → L3 → L4 → L5, with independent gate reviewers.
5. **Requirement Locking**: Planning emits a frozen `requirements-lock.json`; every stage from L3 onward must match its hash and QA must produce traceability evidence.
6. **Conservative Evolution**: Nightly evolution only keeps changes that improve score and still pass doctor.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `bash scripts/bootstrap.sh` | Validate control plane, sync metadata, sync skills, and install cron |
| `python3 -m tools.control_plane doctor` | Run full control-plane self-check |
| `python3 -m tools.control_plane sync-agent-metadata` | Regenerate derived `agents/*/agent.json` |
| `python3 -m tools.control_plane workflow-dry-run` | Simulate the legal workflow path |
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
- Requirement-lock schema validation and drift protection from L3 onward
- Derived metadata parity between registry and every `agents/*/agent.json`
- Independent reviewer validation for every gate
- Review artifact schema validation for `review-passed.json`
- Locked-requirement hash validation before development, QA, and deployment

## Evolution

Every night at 02:00, `.aegis/schedules/nightly-evolution.sh` runs the control-plane evolution command.

- Evolution creates an isolated git worktree
- Each evolvable agent is scored against the shared rubric
- Deterministic low-risk improvements are attempted
- Candidates are kept only if the score improves and `doctor` still passes
- Every result is written to `.aegis/core/evolution.log`

## Recovery

To recover the system on another machine:

```bash
git clone <your-repo> ~/aegis-os
cd ~/aegis-os
bash scripts/bootstrap.sh
```
