import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import backend.agent.tools as tool_package
from backend.agent.tools import (
    DuplicateToolError,
    ToolDefinition,
    ToolNotFoundError,
    ToolRegistry,
    ToolRegistryError,
)


def make_definition(
    name: str = "alpha",
    *,
    version: str | None = None,
    metadata: dict | None = None,
) -> ToolDefinition:
    values: dict[str, object] = {
        "name": name,
        "description": f"Tool {name}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
            "additionalProperties": False,
        },
    }
    if version is not None:
        values["version"] = version
    if metadata is not None:
        values["metadata"] = metadata
    return ToolDefinition(**values)


class ToolRegistryCoreTests(unittest.TestCase):
    def test_empty_registry(self) -> None:
        registry = ToolRegistry()

        self.assertEqual(registry.list_tools(), [])
        self.assertEqual(registry.export_definitions(), [])
        self.assertFalse(registry.exists("alpha"))

        with self.assertRaises(ToolNotFoundError):
            registry.get("alpha")
        with self.assertRaises(ToolNotFoundError):
            registry.unregister("alpha")

    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        definition = make_definition(
            version="1.0.0",
            metadata={"owner": "test"},
        )

        registry.register(definition)
        restored = registry.get("alpha")

        self.assertEqual(restored, definition)
        self.assertIsNot(restored, definition)
        self.assertTrue(registry.exists("alpha"))
        self.assertFalse(registry.exists("beta"))

    def test_list_tools_is_sorted_by_name(self) -> None:
        registry = ToolRegistry()
        for name in ("gamma", "alpha", "beta"):
            registry.register(make_definition(name=name))

        self.assertEqual(
            [definition.name for definition in registry.list_tools()],
            ["alpha", "beta", "gamma"],
        )

    def test_duplicate_registration_preserves_original(self) -> None:
        registry = ToolRegistry()
        original = make_definition(metadata={"owner": "original"})
        replacement = make_definition(metadata={"owner": "replacement"})
        registry.register(original)

        with self.assertRaises(DuplicateToolError) as context:
            registry.register(replacement)

        self.assertEqual(context.exception.tool_name, "alpha")
        self.assertEqual(registry.get("alpha"), original)
        self.assertEqual(len(registry.list_tools()), 1)

    def test_missing_get_raises(self) -> None:
        registry = ToolRegistry()

        with self.assertRaises(ToolNotFoundError) as context:
            registry.get("missing")

        self.assertEqual(context.exception.tool_name, "missing")

    def test_missing_unregister_raises_and_leaves_registry_unchanged(
        self,
    ) -> None:
        registry = ToolRegistry()
        definition = make_definition()
        registry.register(definition)

        with self.assertRaises(ToolNotFoundError) as context:
            registry.unregister("missing")

        self.assertEqual(context.exception.tool_name, "missing")
        self.assertEqual(registry.get("alpha"), definition)
        self.assertEqual(len(registry.list_tools()), 1)

    def test_unregister_removes_and_returns_definition(self) -> None:
        registry = ToolRegistry()
        definition = make_definition(metadata={"nested": {"count": 1}})
        registry.register(definition)

        removed = registry.unregister("alpha")

        self.assertEqual(removed, definition)
        self.assertIsNot(removed, definition)
        self.assertFalse(registry.exists("alpha"))
        with self.assertRaises(ToolNotFoundError):
            registry.get("alpha")

        removed.metadata["nested"]["count"] = 2
        self.assertEqual(definition.metadata["nested"]["count"], 1)

    def test_re_register_after_unregister(self) -> None:
        registry = ToolRegistry()
        definition = make_definition()
        registry.register(definition)
        registry.unregister("alpha")

        registry.register(definition)

        self.assertTrue(registry.exists("alpha"))
        self.assertEqual(registry.get("alpha"), definition)

    def test_register_after_unregister_can_replace_definition(self) -> None:
        registry = ToolRegistry()
        original = make_definition(metadata={"owner": "original"})
        replacement = make_definition(metadata={"owner": "replacement"})
        registry.register(original)
        registry.unregister("alpha")

        registry.register(replacement)

        self.assertEqual(registry.get("alpha"), replacement)


class ToolRegistryDefensiveCopyTests(unittest.TestCase):
    def test_registration_stores_deep_copy(self) -> None:
        registry = ToolRegistry()
        source = make_definition(metadata={"nested": {"count": 1}})
        registry.register(source)

        nested_metadata = source.metadata["nested"]
        self.assertIsInstance(nested_metadata, dict)
        nested_metadata["count"] = 2
        source.input_schema["properties"]["value"]["type"] = "integer"

        restored = registry.get("alpha")
        self.assertEqual(restored.metadata["nested"]["count"], 1)
        self.assertEqual(
            restored.input_schema["properties"]["value"]["type"],
            "string",
        )

    def test_get_returns_deep_copy(self) -> None:
        registry = ToolRegistry()
        definition = make_definition(metadata={"nested": {"count": 1}})
        registry.register(definition)

        first = registry.get("alpha")
        second = registry.get("alpha")
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

        nested_metadata = first.metadata["nested"]
        self.assertIsInstance(nested_metadata, dict)
        nested_metadata["count"] = 2
        first.input_schema["properties"]["value"]["type"] = "integer"

        restored = registry.get("alpha")
        self.assertEqual(restored.metadata["nested"]["count"], 1)
        self.assertEqual(
            restored.input_schema["properties"]["value"]["type"],
            "string",
        )

    def test_list_tools_returns_deep_copies(self) -> None:
        registry = ToolRegistry()
        definition = make_definition(metadata={"nested": {"count": 1}})
        registry.register(definition)

        first = registry.list_tools()[0]
        second = registry.list_tools()[0]
        self.assertIsNot(first, second)
        self.assertEqual(first, second)

        nested_metadata = first.metadata["nested"]
        self.assertIsInstance(nested_metadata, dict)
        nested_metadata["count"] = 2
        first.input_schema["properties"]["value"]["type"] = "integer"

        restored = registry.get("alpha")
        self.assertEqual(restored.metadata["nested"]["count"], 1)
        self.assertEqual(
            restored.input_schema["properties"]["value"]["type"],
            "string",
        )

    def test_export_definitions_returns_isolated_dictionaries(self) -> None:
        registry = ToolRegistry()
        registry.register(
            make_definition(metadata={"nested": {"count": 1}})
        )

        exported = registry.export_definitions()
        exported_metadata = exported[0]["metadata"]
        self.assertIsInstance(exported_metadata, dict)
        exported_metadata["nested"]["count"] = 2

        exported_properties = exported[0]["input_schema"]["properties"]
        self.assertIsInstance(exported_properties, dict)
        exported_properties["value"]["type"] = "integer"

        restored = registry.get("alpha")
        self.assertEqual(restored.metadata["nested"]["count"], 1)
        self.assertEqual(
            restored.input_schema["properties"]["value"]["type"],
            "string",
        )


class ToolRegistrySerializationTests(unittest.TestCase):
    def test_export_definitions_is_sorted_and_json_serializable(self) -> None:
        registry = ToolRegistry()
        registry.register(
            make_definition(
                "beta",
                version="2.0.0",
            )
        )
        registry.register(
            make_definition(
                "alpha",
                version="1.0.0",
                metadata={"nested": {"enabled": True, "levels": [1, 2]}},
            )
        )

        exported = registry.export_definitions()

        self.assertEqual(
            [definition["name"] for definition in exported],
            ["alpha", "beta"],
        )
        self.assertEqual(exported[0]["version"], "1.0.0")
        self.assertEqual(
            exported[0]["metadata"],
            {"nested": {"enabled": True, "levels": [1, 2]}},
        )
        self.assertEqual(
            exported[0]["input_schema"]["type"],
            "object",
        )

        payload = json.dumps(exported)
        self.assertIsInstance(payload, str)

        restored = ToolDefinition.model_validate(exported[0])
        self.assertEqual(restored, registry.get("alpha"))


class ToolRegistryErrorTests(unittest.TestCase):
    def test_error_hierarchy_and_attributes(self) -> None:
        duplicate = DuplicateToolError("alpha")
        missing = ToolNotFoundError("beta")

        self.assertIsInstance(duplicate, ToolRegistryError)
        self.assertIsInstance(missing, ToolRegistryError)
        self.assertEqual(duplicate.tool_name, "alpha")
        self.assertEqual(missing.tool_name, "beta")
        self.assertEqual(str(duplicate), "tool already registered: alpha")
        self.assertEqual(str(missing), "tool not found: beta")


class ToolRegistryConcurrencyTests(unittest.TestCase):
    def test_concurrent_duplicate_registration_allows_one_success(
        self,
    ) -> None:
        registry = ToolRegistry()
        definition = make_definition()
        worker_count = 8
        barrier = Barrier(worker_count)

        def attempt_register(_: int) -> str:
            barrier.wait()
            try:
                registry.register(definition)
            except DuplicateToolError:
                return "duplicate"
            return "registered"

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(
                executor.map(attempt_register, range(worker_count))
            )

        self.assertEqual(results.count("registered"), 1)
        self.assertEqual(
            results.count("duplicate"),
            worker_count - 1,
        )
        self.assertEqual(len(registry.list_tools()), 1)


class ToolRegistryPackageTests(unittest.TestCase):
    def test_package_exports_registry_and_errors(self) -> None:
        self.assertIs(tool_package.ToolRegistry, ToolRegistry)
        self.assertIs(tool_package.ToolRegistryError, ToolRegistryError)
        self.assertIs(tool_package.DuplicateToolError, DuplicateToolError)
        self.assertIs(tool_package.ToolNotFoundError, ToolNotFoundError)


if __name__ == "__main__":
    unittest.main()
