# AEGIS 1.0 Multi-Agent Runtime Architecture

Updated: 2026-04-22

AEGIS 1.0 is not an LLM wrapper and not a raw model router. It is a local agent-CLI orchestration system for Codex CLI, Claude Code, and other host-native runtimes.

The core collaboration loop is:

```text
Task Decomposition
  -> Role Assignment
  -> Runtime Scheduling
  -> Shared Event/Memory Layer
  -> Result Aggregation
  -> Verification and Feedback Iteration
```

## Core Principle

AEGIS treats Codex CLI and Claude Code as executable local agents.

The product object is:

```text
Agent Runtime = local CLI/runtime + role capability + execution contract
```

This is different from:

```text
Model = remote LLM name
```

For compatibility, some internal JSON fields are still named `model`, but the 1.0 product language and command surface should use `agent`, `runtime`, or `agent runtime`.

## Architecture Layers

### 1. Intent Router

The router validates user input and classifies the task:

- task type
- complexity
- preferred collaboration strategy
- mode: speed, balanced, quality, cost

It must reject invalid requests before a session is created.

### 2. Role Planner

The planner maps strategy to roles and stages.

Core roles:

- orchestrator
- planner
- builder
- reviewer
- verifier
- aggregator
- researcher

The planner does not choose abstract LLMs. It binds each role to an agent runtime such as `codex` or `claude`.

### 3. Agent Runtime Registry

The runtime registry describes host-native agents:

```text
codex  -> Codex CLI
claude -> Claude Code
```

Each runtime declares:

- runtime command
- supported roles
- availability check
- optional underlying runtime model parameter

The default 1.0 registry should stay small and concrete. Do not expose remote model names as the primary product concept.

### 4. Scheduler / Collaboration Engine

The collaboration engine is the central scheduler.

Responsibilities:

- execute planned stages
- write lifecycle events
- preserve role/runtime identity
- support feedback loops
- call verification
- stop completion when policy fails

In 1.0, this scheduler is intentionally centralized. Decentralized agent-to-agent autonomy can come later, after the event protocol and recovery model are stable.

### 5. Shared Event And Memory Layer

The current 1.0 memory layer is event-sourced:

```text
.aegis/state/aegis1_sessions.db
.aegis/runs/aegis-1/<session_id>/events.jsonl
.aegis/runs/aegis-1/<session_id>/run_manifest.json
.aegis/runs/aegis-1/<session_id>/summary.md
```

This is the shared memory every role can later read from.

Near-term target:

- global run context
- per-stage outputs
- feedback messages
- verification evidence
- recovery checkpoints

### 6. Communication Pattern

The 1.0 communication pattern is:

```text
stage output -> event store -> next stage prompt/context
```

This is equivalent to a lightweight shared-memory and message-queue pattern, but implemented as durable run events first.

Future expansion:

- explicit message objects
- dependency-aware task DAG
- async worker queue for swarm
- fan-out/fan-in aggregation protocol

### 7. Feedback Iteration

Feedback loops are mandatory for real collaboration.

Current baseline:

- pair mode has bounded review/fix rounds
- pipeline mode requires review, verification, and done gate
- RunPolicy prevents fake `completed`

Next target:

- verifier can send structured feedback to builder
- reviewer can block or request revision with typed reasons
- failed stages can retry with prior artifacts
- recovery can resume from checkpoint instead of replaying the whole request

## Collaboration Modes

### Single

One agent runtime handles a small task.

### Pair

Builder and reviewer collaborate:

```text
builder -> reviewer -> revise or approve -> verification
```

### Pipeline

Eight-stage autopilot:

```text
plan_check -> story_split -> spec -> build -> review -> verify -> done_gate -> delivery
```

### Swarm

Planner splits work, multiple builders execute subtasks, aggregator merges results.

Current state: sequential baseline.

Target state: dependency-aware parallel fan-out/fan-in.

### MoA

Multiple roles produce candidate answers, aggregator synthesizes.

Current state: baseline candidates and aggregation.

Target state: independent agent runtime calls, conflict detection, evidence-based synthesis.

## Product Rules

1. AEGIS should say agent/runtime, not model, in product-facing docs and UI.
2. `--agents` is the preferred explicit selection flag.
3. `--models` remains only as a compatibility alias.
4. Router, plan, runtime, events, and artifacts must preserve the selected agent runtime identity.
5. If a user explicitly selects an agent runtime, AEGIS must not silently replace it.
6. If an explicit agent runtime cannot serve a required role, AEGIS must fail with a clear error.
7. A run can become `completed` only after verification and RunPolicy pass.
8. Shared memory must be durable enough for replay, recovery, and audit.

## Implementation Map

Current code map:

```text
tools/aegis_1/router.py    -> input validation and strategy routing
tools/aegis_1/roles.py     -> role definitions
tools/aegis_1/models.py    -> compatibility-named agent runtime registry
tools/aegis_1/planner.py   -> role/stage plan builder
tools/aegis_1/runtime.py   -> Codex CLI / Claude Code adapters
tools/aegis_1/engine.py    -> central scheduler and feedback loop
tools/aegis_1/session.py   -> sqlite session/event memory
tools/aegis_1/artifacts.py -> durable run artifacts
tools/aegis_1/policy.py    -> completion gate
tools/aegis_1/cockpit.py   -> live terminal cockpit
```

The file name `models.py` is now a compatibility artifact. Future cleanup can rename it to `agent_runtimes.py` after external behavior is stable.

## Scheduler Design Reference

`oh-my-openagent` is useful as a product and architecture reference, but its current public repository is TypeScript/OpenCode-oriented rather than the Python `BaseScheduler` / `DefaultScheduler` structure sometimes described in secondary summaries. The parts AEGIS should absorb are the orchestration principles, not exact class names.

### What AEGIS Should Borrow

#### 1. Centralized lifecycle control

The scheduler owns the full run lifecycle:

```text
request
  -> validate
  -> decompose
  -> assign roles
  -> schedule runtime calls
  -> collect events/results
  -> verify
  -> aggregate
  -> complete or fail
```

Agents should not directly mutate global state. They return results to the scheduler, and the scheduler writes durable events.

#### 2. Separation of planning and execution

The reference architecture separates planner, conductor, and workers. AEGIS should map that into:

```text
IntentRouter       -> classify request
RunPlanner         -> create role/stage plan
CollaborationEngine -> central scheduler/conductor
RuntimeManager     -> execute Codex CLI / Claude Code calls
RunPolicy          -> completion gate
```

Planning decides what should happen. Execution does only what the plan says. Verification decides whether the run may finish.

#### 3. Role-first scheduling

The scheduler should dispatch by role and capability, not by raw model names.

AEGIS role mapping:

```text
planner/reviewer/aggregator/orchestrator -> claude
builder/researcher/verifier              -> codex
```

User-facing selection is `--agents`, with `--models` only as a compatibility alias.

#### 4. Shared event memory

The reference idea of global memory/message queue maps to AEGIS event-sourced memory:

```text
session row
stage_start event
stage_result event
review_feedback event
verification event
done_gate event
policy_passed or policy_violation event
artifact files
```

The scheduler must build downstream context from these durable events instead of invisible in-memory strings.

#### 5. Dependency-aware scheduling

AEGIS should evolve from a simple linear step loop to dependency-aware execution:

```text
serial stage: depends_on previous output
parallel stage: no unresolved dependencies
fan-in stage: waits for worker outputs
feedback stage: loops back with structured review/verifier feedback
```

This is the correct future shape for swarm and MoA.

#### 6. Result aggregation as a first-class step

Aggregation should not be a loose final string. It should be an explicit stage that consumes known inputs:

```text
worker outputs
review findings
verification evidence
unresolved risks
delivery summary
```

For AEGIS 1.0, `aggregator` should become responsible for conflict resolution and final delivery, while `RunPolicy` remains the hard completion gate.

#### 7. Bounded retry and feedback iteration

AEGIS should keep bounded, explainable retries:

```text
reviewer -> REVISE -> builder retry
verifier -> FAILED -> builder retry or failed session
runtime error -> structured retry/fallback policy
```

Every retry must emit a durable event with reason, source stage, target stage, and attempt count.

### What AEGIS Should Not Borrow

#### 1. Do not use hidden LLM fallback as a subtask result

Some generic scheduler designs recover failed subtasks by asking a default LLM to produce a substitute answer. AEGIS should not do that for 1.0.

Reason:

- AEGIS is controlling local agent CLIs, not a generic model pool.
- Silent fallback breaks trust.
- Fake generated results can create false `completed`.

Instead:

```text
explicit runtime unavailable -> clear failure
system default runtime unavailable -> allowed fallback only if declared
verification failed -> failed or explicit retry
policy failed -> failed, never completed
```

#### 2. Do not let agents talk around the scheduler

All communication should pass through event memory until the protocol is stable. Direct agent-to-agent mutation makes recovery and audit difficult.

#### 3. Do not start with distributed scheduling

1.0 should stay centralized. Parallel workers can run inside the central scheduler first. External queues can come later after the event schema, checkpoint schema, and retry rules are stable.

## AEGIS Scheduler Contract

The 1.0 scheduler should satisfy this contract:

1. It registers a run before execution starts.
2. It writes every stage transition as an event.
3. It assigns stages by role and agent runtime capability.
4. It constructs stage context from prior events/artifacts.
5. It supports serial, fan-out, fan-in, and feedback loop semantics.
6. It never marks a run completed before RunPolicy passes.
7. It never silently replaces an explicitly selected agent runtime.
8. It records failures with structured recovery hints.
9. It makes aggregation and verification visible stages, not hidden post-processing.
10. It keeps the cockpit renderable from durable state alone.

## Scheduler Implementation Roadmap

### M1: Current baseline

Already present:

- centralized `CollaborationEngine`
- sequential stage execution
- pair review/fix loop
- session/event store
- RunPolicy gate
- live cockpit from session events

### M2: Dependency-aware stage graph

Add to `RunStep`:

```text
depends_on: list[str]
group: str | None
attempt: int
```

Then replace the simple sequential loop with:

```text
ready queue -> running set -> completed/failed set -> fan-in aggregation
```

### M3: Swarm fan-out/fan-in

Planner emits:

```text
S1 split
S2a worker
S2b worker
S2c worker
S3 aggregate depends_on=[S2a,S2b,S2c]
S4 verify depends_on=[S3]
```

The scheduler may execute worker steps concurrently once runtime isolation is reliable.

### M4: Structured retry policy

Add typed retry events:

```text
retry_requested
retry_started
retry_exhausted
fallback_declined
```

Retries must be bounded and visible in cockpit.

### M5: Checkpoint resume

Resume should pick up from the latest safe stage boundary:

```text
last completed stage
failed stage
available artifacts
policy violations
retry count
```

This is the point where `session resume` becomes true checkpoint recovery instead of request replay.
