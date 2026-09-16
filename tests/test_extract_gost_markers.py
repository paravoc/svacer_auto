import importlib.util
import gzip
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "extract_gost_markers.py"
SPEC = importlib.util.spec_from_file_location("extract_gost_markers", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sarif_result(invariant: str, severity: str = "Major"):
    return {
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "/app/a.go"},
                    "region": {"startLine": 7},
                }
            }
        ],
        "properties": {
            "warnClass": "DEREF",
            "checker_severity": severity,
            "invariant": invariant,
        },
    }


def reference(result, result_index):
    return {"run_index": 0, "result_index": result_index, "result": result, "run": {}}


def csv_row(severity: str = "Major"):
    return {
        "Severity": severity,
        "Checker": "DEREF",
        "File": "/app/a.go",
        "Line": "7",
        "_csv_row": "2",
    }


class ExtractGostMarkersTests(unittest.TestCase):
    def test_markup_gzip_is_rejected_with_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Markup_project_branch.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write('{"invariant":"abc"}\n')
            with self.assertRaisesRegex(MODULE.ExtractError, "Markup2"):
                MODULE.read_json(path)

    def test_pasted_local_file_uri_is_accepted(self):
        path = MODULE.path_from_paste("file:///C:/Temp/markers.csv")
        self.assertEqual(path.drive.casefold(), "c:")
        self.assertEqual(path.name, "markers.csv")

    def test_known_scan_prefix_is_detected(self):
        rows = [csv_row(), csv_row()]
        self.assertEqual(MODULE.detect_strip_prefix(rows), "/app/")

    def test_duplicate_rows_are_not_deduplicated(self):
        references = [
            reference(sarif_result("one"), 10),
            reference(sarif_result("two"), 11),
        ]
        selected = MODULE.select_results(references, [csv_row(), csv_row()])
        self.assertEqual(
            [item["result"]["properties"]["invariant"] for item in selected],
            ["one", "two"],
        )

    def test_severity_disambiguates_same_checker_file_and_line(self):
        references = [
            reference(sarif_result("major", "Major"), 10),
            reference(sarif_result("critical", "Critical"), 11),
        ]
        selected = MODULE.select_results(references, [csv_row("Critical")])
        self.assertEqual(selected[0]["result"]["properties"]["invariant"], "critical")

    def test_ambiguous_subset_fails_instead_of_guessing(self):
        references = [
            reference(sarif_result("one"), 10),
            reference(sarif_result("two"), 11),
        ]
        with self.assertRaises(MODULE.ExtractError):
            MODULE.select_results(references, [csv_row()])

    def test_trace_roles_and_all_steps_are_preserved(self):
        result = sarif_result("one")
        result["codeFlows"] = [
            {
                "message": {"text": "possible null"},
                "threadFlows": [
                    {
                        "message": {"text": "source"},
                        "locations": [
                            {
                                "location": {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "/app/a.go"},
                                        "region": {"startLine": 3, "startColumn": 5},
                                    },
                                    "message": {"text": "function result"},
                                }
                            },
                            {
                                "location": {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "/app/a.go"},
                                        "region": {"startLine": 7, "startColumn": 9},
                                    },
                                    "message": {"text": "dereference"},
                                }
                            },
                        ],
                    }
                ],
            }
        ]
        trace = MODULE.normalize_trace(result, "/app/")
        self.assertEqual(trace[0]["role"], "possible null")
        self.assertEqual(trace[0]["threads"][0]["role"], "source")
        self.assertEqual(len(trace[0]["threads"][0]["steps"]), 2)
        self.assertEqual(trace[0]["threads"][0]["steps"][0]["repo_path"], "a.go")


if __name__ == "__main__":
    unittest.main()
