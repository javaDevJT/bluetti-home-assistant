import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


DIAGNOSTIC_LOG_SNIPPETS = (
    "BLUETTI setup product summary",
    "BLUETTI periodic runtime state summary",
    "BLUETTI setup runtime state summary",
    "BLUETTI app state override summary",
    "BLUETTI app direct lookup summary",
    "BLUETTI app selected home-device payload",
    "BLUETTI app home devices summary",
    "Hub A1 app lookup summary",
    "Hub A1 selected field source summary",
    "Hub A1 app home serial summary",
    "Hub A1 related app telemetry fallback summary",
    "Hub A1 built state summary",
    "Hub A1 optional telemetry summary",
)


def _log_messages(source: str, level: str) -> set[str]:
    tree = ast.parse(source)
    messages: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != level:
            continue
        if not node.args:
            continue
        message = node.args[0]
        if isinstance(message, ast.Constant) and isinstance(message.value, str):
            messages.add(message.value)
    return messages


class DebugLoggingContractTests(unittest.TestCase):
    def test_diagnostic_summaries_are_debug_only(self):
        init_source = (ROOT / "custom_components" / "bluetti" / "__init__.py").read_text(
            encoding="utf-8"
        )
        product_client_source = (
            ROOT / "custom_components" / "bluetti" / "api" / "product_client.py"
        ).read_text(encoding="utf-8")
        sources = f"{init_source}\n{product_client_source}"

        warning_messages = _log_messages(sources, "warning")
        debug_messages = _log_messages(sources, "debug")

        for snippet in DIAGNOSTIC_LOG_SNIPPETS:
            self.assertFalse(
                any(snippet in message for message in warning_messages),
                f"{snippet!r} must not be logged at warning level",
            )
            self.assertTrue(
                any(snippet in message for message in debug_messages),
                f"{snippet!r} must remain available at debug level",
            )

        self.assertIn("isEnabledFor(logging.DEBUG)", sources)


if __name__ == "__main__":
    unittest.main()
