import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from analysis.json_utils import JSONParseError, parse_json_response, repair_json_text, validate_schema


class RepairJsonTextTests(unittest.TestCase):
    def test_strips_code_fences(self):
        self.assertEqual(repair_json_text('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_extracts_json_from_surrounding_prose(self):
        raw = 'Sure, here is the JSON:\n{"a": 1}\nLet me know if you need anything else.'
        self.assertEqual(repair_json_text(raw), '{"a": 1}')

    def test_removes_trailing_commas(self):
        self.assertEqual(repair_json_text('{"a": 1, "b": [1, 2,],}'), '{"a": 1, "b": [1, 2]}')

    def test_normalizes_smart_quotes(self):
        self.assertEqual(repair_json_text('{“a”: ‘1’}'), '{"a": \'1\'}')


class ParseJsonResponseTests(unittest.TestCase):
    def test_parses_clean_json(self):
        self.assertEqual(parse_json_response('{"a": 1}'), {"a": 1})

    def test_repairs_and_parses_fenced_json_with_trailing_comma(self):
        raw = '```json\n{"a": 1, "b": [1, 2,],}\n```'
        self.assertEqual(parse_json_response(raw), {"a": 1, "b": [1, 2]})

    def test_unrecoverable_garbage_raises_json_parse_error(self):
        with self.assertRaises(JSONParseError):
            parse_json_response("this is not json at all {{{")

    def test_none_raises_json_parse_error(self):
        with self.assertRaises(JSONParseError):
            parse_json_response(None)


class ValidateSchemaTests(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "required": ["summary"],
        "properties": {
            "summary": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }

    def test_valid_payload_has_no_errors(self):
        errors = validate_schema({"summary": "ok", "tags": ["a", "b"]}, self.SCHEMA)
        self.assertEqual(errors, [])

    def test_missing_required_field_is_an_error(self):
        errors = validate_schema({"tags": []}, self.SCHEMA)
        self.assertTrue(any("summary" in e for e in errors))

    def test_wrong_type_for_required_field_is_an_error(self):
        errors = validate_schema({"summary": 123}, self.SCHEMA)
        self.assertTrue(any("summary" in e for e in errors))

    def test_wrong_item_type_in_array_is_an_error(self):
        errors = validate_schema({"summary": "ok", "tags": [1, 2]}, self.SCHEMA)
        self.assertTrue(any("tags" in e for e in errors))

    def test_non_object_payload_is_an_error(self):
        errors = validate_schema(["not", "an", "object"], self.SCHEMA)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
