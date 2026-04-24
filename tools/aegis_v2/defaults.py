from __future__ import annotations

from textwrap import dedent


DEFAULT_REGISTRY_YAML = dedent(
    """
    version: "2.0"

    models:
      claude-opus-4-7:
        provider: anthropic
        runtime: claude-code-cli
        capabilities:
          - architecture_design
          - complex_reasoning
          - security_audit
          - long_context
        context_window: 200000
        cost_per_1k_tokens: 0.015
        specialties:
          - system_architecture
          - algorithm_design
          - security_review
        config:
          max_thinking_tokens: 32000
          temperature: 0.7

      claude-sonnet-4-6:
        provider: anthropic
        runtime: claude-code-cli
        capabilities:
          - code_generation
          - refactoring
          - debugging
          - code_review
        context_window: 200000
        cost_per_1k_tokens: 0.003
        specialties:
          - full_stack_development
          - api_design
          - testing
        config:
          temperature: 0.5

      codex:
        provider: openai
        runtime: codex-cli
        capabilities:
          - fast_code_generation
          - quick_fixes
          - boilerplate
          - autocomplete
        context_window: 128000
        cost_per_1k_tokens: 0.001
        specialties:
          - rapid_prototyping
          - syntax_correction
          - simple_tasks
        config:
          temperature: 0.3

      o3-mini:
        provider: openai
        runtime: api
        capabilities:
          - fast_response
          - simple_reasoning
        context_window: 64000
        cost_per_1k_tokens: 0.0005
        specialties:
          - quick_questions
          - simple_explanations

      local-llm:
        provider: ollama
        runtime: local
        capabilities:
          - offline_work
          - privacy_sensitive
        context_window: 32000
        cost_per_1k_tokens: 0
        specialties:
          - private_code_review
    """
).strip() + "\n"


DEFAULT_CONFIG_YAML = dedent(
    """
    version: "2.0"

    models:
      enabled:
        - claude-opus-4-7
        - claude-sonnet-4-6
        - codex
      default_strategy: balanced
      overrides:
        claude-opus-4-7:
          max_budget_per_task: 5.00
          temperature: 0.7
        codex:
          max_budget_per_task: 1.00
          temperature: 0.3

    collaboration:
      pair_programming:
        max_iterations: 3
        max_stagnant_rounds: 2
        coder_model: codex
        reviewer_model: claude-sonnet-4-6
      moa:
        discussion_rounds: 2
        max_peer_findings: 2
        expert_roles:
          - name: correctness
            focus: Validate whether the answer is technically correct and complete against the request.
          - name: risk
            focus: Find hidden risks, regressions, edge cases, and operational failure modes.
          - name: maintainability
            focus: Judge long-term maintainability, clarity, change surface, and testability.
      swarm:
        default_workers: 3
        worker_model: codex
        aggregator_model: claude-sonnet-4-6
        splitter_model: claude-sonnet-4-6
      pipeline:
        stages:
          - name: design
            model: claude-opus-4-7
            condition: complexity > 7
          - name: code
            model: codex
          - name: test
            model: codex
          - name: review
            model: claude-sonnet-4-6

    routing:
      task_patterns:
        architecture: { strategy: single, model: claude-opus-4-7 }
        feature_impl: { strategy: pair, priority: speed }
        bug_fix: { strategy: pipeline, stages: [analyze, fix, verify] }
        code_review: { strategy: swarm, workers: 2 }
        test_gen: { strategy: swarm, workers: 3 }
        refactoring: { strategy: pair }
      context_thresholds:
        use_long_context_model: 100000
        truncate_context: 150000

    cost_control:
      daily_budget: 50.00
      per_task_budget: 10.00
      alerts:
        - at: "80%"
        - at: "100%"

    performance:
      parallel_execution: true
      max_concurrent_models: 3
      cache_responses: true
      cache_ttl: 3600

    runtime:
      retries: 2
      timeout_seconds:
        default: 120
        claude-code-cli: 180
        codex-cli: 180
        api: 90
        local: 120
      fallback:
        prefer_same_runtime: true
        prefer_capability_match: true
    """
).strip() + "\n"
