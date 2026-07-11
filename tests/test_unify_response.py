import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "bluetti"
    / "api"
    / "unify_response.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("unify_response", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("unify_response module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UnifyResponseTests(unittest.TestCase):
    def setUp(self):
        self.unify_response = load_module()

    def test_preserves_optional_message_and_code_fields(self):
        response = self.unify_response.UnifyResponse[dict].model_validate(
            {
                "msgId": "message-id",
                "msgCode": -2,
                "code": -2,
                "message": "The parameter deviceSn can not be empty.",
                "data": None,
            }
        )

        self.assertEqual(response.msgCode, -2)
        self.assertEqual(response.code, -2)
        self.assertEqual(response.message, "The parameter deviceSn can not be empty.")


if __name__ == "__main__":
    unittest.main()
