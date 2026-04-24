import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.aegis_v2.config import build_paths
from tools.aegis_v2.defaults import DEFAULT_REGISTRY_YAML
from tools.aegis_v2.registry import ModelRegistry
from tools.aegis_v2.router import TaskRouter
from tools.aegis_v2.types import RoutingStrategy, TaskType


class RegistryRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_dir = Path(tempfile.mkdtemp(prefix="aegis-v2-registry-router-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.workspace_dir, ignore_errors=True)

    def write_registry(self, payload: dict) -> None:
        paths = build_paths(self.workspace_dir)
        paths.registry_path.parent.mkdir(parents=True, exist_ok=True)
        paths.registry_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def write_config(self, payload: dict) -> None:
        paths = build_paths(self.workspace_dir)
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        paths.config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def test_default_model_registry_entries_match_router_contract(self) -> None:
        payload = yaml.safe_load(DEFAULT_REGISTRY_YAML)

        self.assertEqual(payload["version"], "2.0")
        self.assertIn("models", payload)
        self.assertGreaterEqual(len(payload["models"]), 1)

        required_model_keys = {
            "provider",
            "runtime",
            "capabilities",
            "context_window",
            "cost_per_1k_tokens",
            "specialties",
        }
        for name, model in payload["models"].items():
            with self.subTest(model=name):
                self.assertTrue(required_model_keys.issubset(model))
                self.assertIsInstance(model["capabilities"], list)
                self.assertIsInstance(model["specialties"], list)
                self.assertIsInstance(model["context_window"], int)
                self.assertIsInstance(model["cost_per_1k_tokens"], (int, float))

    def test_repository_agent_registry_schema_contract_is_present(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / ".aegis" / "core" / "registry.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["title"], "AEGIS Registry")
        self.assertEqual(schema["type"], "object")
        self.assertEqual(
            schema["required"],
            ["version", "last_updated", "capabilities", "workflow_types", "agents"],
        )
        self.assertIn("required", schema["properties"]["agents"]["items"])
        self.assertIn("capabilities", schema["properties"]["agents"]["items"]["required"])
        self.assertIn("workflow_types", schema["properties"]["agents"]["items"]["required"])

    def test_model_registry_loads_schema_fields_and_enabled_lookup_order(self) -> None:
        self.write_registry(
            {
                "version": "2.0",
                "models": {
                    "alpha": {
                        "provider": "openai",
                        "runtime": "codex-cli",
                        "capabilities": ["testing", "code_review"],
                        "context_window": 1000,
                        "cost_per_1k_tokens": 0.25,
                        "specialties": ["unit_tests"],
                        "config": {"temperature": 0.1},
                    },
                    "beta": {
                        "provider": "anthropic",
                        "runtime": "claude-code-cli",
                        "capabilities": ["architecture_design"],
                        "context_window": 2000,
                        "cost_per_1k_tokens": 0.5,
                        "specialties": ["architecture"],
                    },
                    "broken": "not-a-model-object",
                },
            }
        )
        self.write_config(
            {
                "version": "2.0",
                "models": {
                    "enabled": ["beta", "missing", "alpha"],
                    "default_strategy": "balanced",
                },
            }
        )

        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))

        self.assertEqual(registry.names(), ["alpha", "beta"])
        self.assertEqual([model.name for model in registry.enabled_models()], ["beta", "alpha"])
        alpha = registry.get("alpha")
        self.assertEqual(alpha.provider, "openai")
        self.assertEqual(alpha.runtime, "codex-cli")
        self.assertEqual(alpha.capabilities, ["testing", "code_review"])
        self.assertEqual(alpha.context_window, 1000)
        self.assertEqual(alpha.cost_per_1k_tokens, 0.25)
        self.assertEqual(alpha.specialties, ["unit_tests"])
        self.assertEqual(alpha.config, {"temperature": 0.1})

    def test_available_model_names_uses_enabled_lookup_and_skips_unknown_models(self) -> None:
        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))
        with patch.object(registry, "check_model") as check_model:
            check_model.side_effect = lambda name: type("Health", (), {"available": name == "codex"})()

            self.assertEqual(registry.available_model_names(names=["missing", "codex", "local-llm"]), ["codex"])

    def test_router_testing_request_routes_to_swarm_with_schema_registered_models(self) -> None:
        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))
        router = TaskRouter(registry)

        decision = router.route("generate unit tests for registry.py and router.py")

        self.assertEqual(decision.task_type, TaskType.TESTING)
        self.assertEqual(decision.strategy, RoutingStrategy.SWARM)
        self.assertEqual(decision.models, ["codex", "claude-sonnet-4-6"])
        self.assertGreater(decision.estimated_cost, 0)
        self.assertLess(decision.estimated_time_seconds, 90)
        self.assertIn("classified as testing", decision.rationale[0])

    def test_router_explicit_model_query_filters_unknown_names_and_preserves_order(self) -> None:
        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))
        router = TaskRouter(registry)

        decision = router.route(
            "review the runtime bridge changes",
            {"models": "missing, codex, claude-sonnet-4-6", "strategy": "swarm"},
        )

        self.assertEqual(decision.task_type, TaskType.CODE_REVIEW)
        self.assertEqual(decision.strategy, RoutingStrategy.SWARM)
        self.assertEqual(decision.models, ["codex", "claude-sonnet-4-6"])

    def test_router_falls_back_to_first_enabled_model_when_rules_reference_disabled_models(self) -> None:
        self.write_config(
            {
                "version": "2.0",
                "models": {
                    "enabled": ["codex"],
                    "default_strategy": "quality",
                },
            }
        )
        registry = ModelRegistry.from_workspace(build_paths(self.workspace_dir))
        router = TaskRouter(registry)

        decision = router.route("design the module architecture")

        self.assertEqual(decision.task_type, TaskType.ARCHITECTURE)
        self.assertEqual(decision.strategy, RoutingStrategy.SINGLE)
        self.assertEqual(decision.models, ["codex"])

    def test_router_rejects_empty_and_ambiguous_messages_before_routing(self) -> None:
        router = TaskRouter(ModelRegistry.from_workspace(build_paths(self.workspace_dir)))

        with self.assertRaisesRegex(ValueError, "request cannot be empty"):
            router.route("   ")
        with self.assertRaisesRegex(ValueError, "too ambiguous"):
            router.route("优化一下")


if __name__ == "__main__":
    unittest.main()
