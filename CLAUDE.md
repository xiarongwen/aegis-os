# AEGIS (Agent Evolution & Governance via Git Integration System)

> Git-Native Multi-Agent Operating System for Enterprise AI Development  
> Version: 1.0.0  
> Base: Claude Code CLI

## Core Philosophy

1. **Git is the OS**: All state, version control, and evolution history lives in Git.
2. **Agent = Skill + Metadata**: Every agent is a subdirectory in `agents/` with `SKILL.md` and `agent.json`.
3. **Strict Gated Flow**: L1 → L2 → L3 → L4 → L5, with independent Review Agents at every gate.
4. **Nightly Self-Evolution**: `darwin-skill` runs at 02:00 daily, optimizing each agent. Only improvements are kept (git ratchet).
5. **Pluggable**: Add/remove agents by adding/removing directories. Symlinks auto-update via `bootstrap.sh`.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `bash scripts/bootstrap.sh` | Sync all agents to `~/.claude/skills/` and install cron |
| `bash .aegis/hooks/pre-agent-run.sh <agent> <workflow>` | Validate before running an agent |
| `bash .aegis/hooks/post-agent-run.sh <agent> <workflow>` | Commit agent outputs |
| `bash .aegis/schedules/nightly-evolution.sh` | Manually trigger agent evolution |
| `cat .aegis/core/registry.json` | List all registered agents |

## Workflow States

```
INIT → L1_RESEARCH → L1_REVIEW → L2_PLANNING → L2_REVIEW
  → L3_DEVELOP → L3_CODE_REVIEW → L3_SECURITY_AUDIT
  → L4_VALIDATE → L4_REVIEW → L5_DEPLOY → L5_REVIEW → DONE
```

If any gate fails 3 times, workflow enters **BLOCKED**.
If security audit finds critical issues, workflow enters **BLOCKED**.

## Directory Rules (Enforced)

- `agents/market-research` → writes `workflows/{id}/l1-intelligence/`
- `agents/prd-architect` → reads L1, writes `workflows/{id}/l2-planning/`
- `agents/frontend-squad` → reads L2, writes `workflows/{id}/l3-dev/frontend/`
- `agents/backend-squad` → reads L2, writes `workflows/{id}/l3-dev/backend/`
- `agents/code-reviewer` → reads L3, writes `workflows/{id}/l3-dev/code-review-report.md`
- `agents/security-auditor` → reads L3, writes `workflows/{id}/l3-dev/security-scan-report.md`
- `agents/qa-validator` → reads L3/L4, writes `workflows/{id}/l4-validation/`
- `agents/deploy-sre` → reads L4, writes `workflows/{id}/l5-release/`

## Gate Review Scores

| Gate | Reviewer | Min Score |
|------|----------|-----------|
| L1 | Independent sub-agent evaluation | 8.0 |
| L2 | Independent sub-agent evaluation | 8.0 |
| L3 Code | code-reviewer | 8.0 |
| L3 Security | security-auditor | 9.0 |
| L4 QA | qa-validator | 8.5 |
| L5 Deploy | deploy-sre | 9.0 |

## When This File is Loaded

Claude Code reads `CLAUDE.md` automatically when entering this directory. This means:
- Any `claude code` session started in `~/aegis-os/` knows the entire system
- The Orchestrator agent (`agents/orchestrator/SKILL.md`) can be invoked naturally

## How to Start a Workflow

Tell Claude:
> "启动 AEGIS 工作流，项目名是 my-saas-platform，需求是做一个高校 SaaS 学习平台"

Claude (as Orchestrator) will:
1. Run `bootstrap.sh` if needed
2. Create `workflows/my-saas-platform/`
3. Spawn `market-research` agent
4. Continue through gates automatically

## Evolution

Every night at 02:00, `nightly-evolution.sh` creates a git worktree and runs `darwin-skill` on each `evolution: true` agent.

- Improved? → `git commit` on branch `auto-evolve/YYYYMMDD-HHMMSS`
- Not improved? → `git checkout HEAD -- agent_dir/` and `git commit --allow-empty`

Merge evolution branches weekly or when scores look good.

## Cross-Machine Recovery

```bash
git clone <your-repo> ~/aegis-os
cd ~/aegis-os
bash scripts/bootstrap.sh
```

All agents and their skills are restored in under 2 minutes.
