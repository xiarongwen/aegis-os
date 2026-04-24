---
description: Invoke AEGIS v2.0 multi-model collaboration engine for intelligent task routing and multi-model coding assistance.
argument-hint: [pattern] [request] [--mode {quality,speed,cost,balanced}] [--models model1,model2] [--budget amount] [--execute|--simulate]
---

You are invoking AEGIS v2.0 multi-model collaboration via `/aegis-v2`.

User request:

$ARGUMENTS

## Quick Usage

```bash
# Auto-route (let AEGIS choose the best pattern)
/aegis-v2 implement JWT authentication

# Force specific collaboration pattern
/aegis-v2 pair fix the SQL injection bug
/aegis-v2 swarm generate test cases for payment module
/aegis-v2 pipeline build a user management system
/aegis-v2 moa review this architecture design

# Control quality/speed/cost
/aegis-v2 "complex task" --mode quality --budget 10.00
/aegis-v2 "simple task" --mode cost

# Preview routing decision without executing
/aegis-v2 router dry-run "implement feature"
```

## Available Patterns

| Pattern | Best For | Models | Description |
|---------|----------|--------|-------------|
| `pair` | Bug fixes, refactoring | Coder + Reviewer | Iterative review/fix until LGTM |
| `swarm` | Test generation, docs | Multiple workers | Parallel subtask execution |
| `pipeline` | Complex features | Stage-specific | Design → Code → Test → Review |
| `moa` | Code review, decisions | Multiple experts | Expert perspectives + synthesis |

## Full Options

```bash
# Pattern selection (optional - auto-detected if omitted)
pair|swarm|pipeline|moa

# Mode selection
--mode {quality,speed,cost,balanced}

# Model override
--models claude-opus-4-7,codex,local-llm

# Budget limit (USD)
--budget 5.00

# Execution mode
--execute    # Real API calls
--simulate   # Simulate execution (default for dry-run)

# Output format
--format json

# Use tmux bridge
--bridge
```

## Session Management

```bash
# List sessions
/aegis-v2 session list

# Show session details
/aegis-v2 session show <session_id>

# Resume a session
/aegis-v2 session resume <session_id>

# Recover and modify a session
/aegis-v2 session recover <session_id> --mode quality
```

## Model Information

```bash
# List available models
/aegis-v2 models list

# Test model availability
/aegis-v2 models test
```

## Cost Tracking

```bash
# View cost summary
/aegis-v2 cost report
```

## How It Works

1. **Task Classification**: AEGIS analyzes your request and classifies it (architecture, code_gen, debugging, etc.)
2. **Strategy Selection**: Based on task type and mode, selects the optimal collaboration pattern
3. **Model Routing**: Chooses the best model(s) for the task and strategy
4. **Execution**: Runs the collaboration pattern with context sharing between models
5. **Result Delivery**: Returns the final output with cost and execution details

## Examples by Use Case

### Bug Fix
```bash
/aegis-v2 pair "Fix the null pointer exception in user service"
```

### Feature Implementation
```bash
/aegis-v2 pipeline "Design and implement OAuth2 authentication"
```

### Code Review
```bash
/aegis-v2 moa "Review the API design for security and scalability"
```

### Test Generation
```bash
/aegis-v2 swarm "Generate comprehensive tests for the order processing module"
```

### Quick Prototype
```bash
/aegis-v2 "Create a simple todo app" --mode speed --budget 2.00
```

### Architecture Design
```bash
/aegis-v2 "Design a microservices architecture for e-commerce" --mode quality
```

## Tips

- Use `--mode quality` for important tasks where accuracy matters
- Use `--mode cost` for simple tasks to save money
- Use `--mode speed` when you need quick results
- Use `router dry-run` first to see the plan without spending money
- Set `--budget` to control costs for exploratory tasks

Read full documentation in `agents/aegis/SKILL-v2.md`.
