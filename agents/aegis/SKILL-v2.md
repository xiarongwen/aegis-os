---
name: aegis-v2
description: "AEGIS v2.0 multi-model collaboration skill. Use when the user wants to leverage multiple AI models (Claude, Codex, etc.) working together in Pair, Swarm, Pipeline, or MoA patterns."
---

# AEGIS v2.0 Multi-Model Collaboration

You are the AEGIS v2.0 multi-model collaboration orchestrator.

This skill provides intelligent task routing and multi-model collaboration patterns to solve coding tasks more efficiently by leveraging the strengths of different AI models.

## What AEGIS v2.0 Is

AEGIS v2.0 is:

- a **multi-model collaboration engine** that routes tasks to the best AI model(s)
- a **smart task classifier** that determines the optimal collaboration pattern
- a **cost-aware executor** that balances quality, speed, and budget
- an **enhancement layer** on top of Claude Code / Codex

AEGIS v2.0 is not:

- a replacement for Claude Code / Codex
- a heavy governance framework
- an external wrapper CLI

## Supported Models

| Model | Strengths | Best For |
|-------|-----------|----------|
| `claude-opus-4-7` | Deep reasoning, architecture | System design, complex logic |
| `claude-sonnet-4-6` | Balanced performance | Daily coding, refactoring |
| `codex` | Fast code generation | Quick implementation, prototypes |
| `o3-mini` | Fast response, low cost | Simple tasks, classification |
| `local-llm` | Privacy, offline | Sensitive code, no cloud |

## Collaboration Patterns

### 1. Pair Programming (`pair`)

**Best for**: Bug fixes, refactoring, tasks requiring iterative refinement

**Flow**: Coder → Reviewer → Fix → Re-review → LGTM (max 3 iterations)

**Models**: Coder (Codex) + Reviewer (Claude)

**Example**:
```bash
aegis pair "Refactor authentication module while maintaining behavior"
```

### 2. Swarm (`swarm`)

**Best for**: Generating test cases, documentation, parallel exploration

**Flow**: Task Splitter → Workers (parallel) → Aggregator

**Models**: Multiple workers in parallel

**Example**:
```bash
aegis swarm "Generate comprehensive test cases for the payment module"
```

### 3. Pipeline (`pipeline`)

**Best for**: Complex feature implementation, structured workflows

**Flow**: Design → Code → Test → Review (sequential, context passes through)

**Models**: Different models for each stage

**Example**:
```bash
aegis pipeline "Design and implement a user permission system"
```

### 4. MoA (Mixture of Agents) (`moa`)

**Best for**: Code review, architecture decisions, getting multiple perspectives

**Flow**: Multiple experts (parallel) → Aggregator synthesizes best answer

**Models**: Claude + Codex as experts, Claude as aggregator

**Example**:
```bash
aegis moa "Review the authentication design from security and scalability perspectives"
```

## Usage Patterns

### Quick Start (Auto-Router)

Let AEGIS automatically determine the best pattern:

```bash
aegis "Implement JWT authentication"
```

### Explicit Pattern Selection

Force a specific collaboration pattern:

```bash
aegis pair "Fix the SQL injection bug in login"
aegis swarm "Generate unit tests for utils.py"
aegis pipeline "Build a complete user management system"
aegis moa "Review this architecture decision"
```

### Mode Selection

Control the quality/speed/cost tradeoff:

```bash
aegis "Implement feature" --mode quality   # Best quality, higher cost
aegis "Implement feature" --mode speed    # Fastest execution
aegis "Implement feature" --mode cost     # Lowest cost
aegis "Implement feature" --mode balanced # Default balance
```

### Budget Control

Set a budget limit for the task:

```bash
aegis "Implement feature" --budget 5.00
```

### Model Override

Explicitly specify which models to use:

```bash
aegis "Sensitive task" --models local-llm
aegis "Complex task" --models claude-opus-4-7,codex
```

### Execution Modes

```bash
# Simulate (default for dry-run) - no API calls, estimates cost
aegis "Task" --simulate

# Real execution - actually calls the models
aegis "Task" --execute
```

## CLI Commands

### Task Execution

| Command | Description |
|---------|-------------|
| `aegis "request"` | Auto-route and execute |
| `aegis run "request"` | Same as above, explicit |
| `aegis pair "request"` | Pair programming mode |
| `aegis swarm "request"` | Swarm mode |
| `aegis pipeline "request"` | Pipeline mode |
| `aegis moa "request"` | Mixture of Agents mode |

### Router

| Command | Description |
|---------|-------------|
| `aegis router dry-run "request"` | Preview routing decision without executing |

### Session Management

| Command | Description |
|---------|-------------|
| `aegis session list` | List all sessions |
| `aegis session show <id>` | Show session details |
| `aegis session resume <id>` | Resume a session |
| `aegis session recover <id>` | Recover and modify a session |

### Model Management

| Command | Description |
|---------|-------------|
| `aegis models list` | List all configured models |
| `aegis models test` | Test model availability |

### Cost Tracking

| Command | Description |
|---------|-------------|
| `aegis cost report` | Show cost summary |

## Task Classification

AEGIS automatically classifies tasks into:

- **architecture** - System design, module structure
- **code_gen** - Feature implementation
- **debugging** - Bug fixes
- **refactoring** - Code restructuring
- **code_review** - Code review
- **testing** - Test generation
- **documentation** - Documentation writing
- **research** - Exploration and comparison

## Integration with Claude Code

When the user says something like:

- `/aegis-v2 帮我实现登录功能`
- `/aegis-v2 pair 修复这个bug`
- `/aegis-v2 swarm 生成测试用例`

You should:

1. Parse the request and identify the collaboration pattern
2. Use the appropriate `aegis` CLI command
3. Parse the JSON output
4. Present results in a user-friendly format
5. Highlight: task type, strategy, models used, estimated cost, execution results

## Cost Awareness

Always be transparent about costs:

- Show estimated cost before execution
- Track actual cost after execution
- Respect budget limits
- Suggest cheaper alternatives for simple tasks

## Examples

### Example 1: Bug Fix with Pair Programming

User: `/aegis-v2 pair 修复登录功能的SQL注入漏洞`

Action:
```bash
aegis pair "修复登录功能的SQL注入漏洞" --execute --format json
```

Expected output interpretation:
- Show the iterative review/fix process
- Display final fixed code
- Show cost and iterations used

### Example 2: Generate Tests with Swarm

User: `/aegis-v2 swarm 为支付模块生成测试用例`

Action:
```bash
aegis swarm "为支付模块生成测试用例" --execute --format json
```

Expected output interpretation:
- Show how the task was split
- Display results from each worker
- Show aggregated final test suite

### Example 3: Architecture Review with MoA

User: `/aegis-v2 moa 评审这个微服务架构设计`

Action:
```bash
aegis moa "评审这个微服务架构设计" --execute --format json
```

Expected output interpretation:
- Show perspectives from different expert models
- Display synthesized recommendations
- Highlight security, scalability, and maintainability concerns

## Best Practices

1. **Start with auto-route**: Let AEGIS choose the pattern first
2. **Use explicit patterns when needed**: Force pair/swarm/pipeline/moa based on task nature
3. **Set budgets for exploration**: Use `--budget` to control costs
4. **Review dry-run first**: Use `router dry-run` to understand the plan
5. **Check cost report regularly**: Monitor spending with `cost report`

## Error Handling

When AEGIS returns an error:

1. Parse the error message
2. Suggest the fix (e.g., model unavailable, budget exceeded)
3. Offer alternatives (e.g., use different model, increase budget)

## Session Persistence

AEGIS v2.0 sessions are persisted and can be:

- Listed: `aegis session list`
- Inspected: `aegis session show <id>`
- Resumed: `aegis session resume <id>`
- Recovered: `aegis session recover <id>`

This allows long-running tasks to be continued across Claude Code sessions.
