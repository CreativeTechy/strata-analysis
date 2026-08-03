import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from services.pipeline import pipeline


class PipelineModuleImportTests(unittest.TestCase):
    """pipeline.py's own logic is subprocess orchestration (not practically
    unit-testable without spawning real scrapy/enrich subprocesses) - it
    delegates the actual diagnostics parsing/summarizing to
    services/pipeline/source_diagnostics.py, see test_source_diagnostics.py.
    This just guards the wiring between them stays importable."""

    def test_module_exposes_diagnostics_helpers_it_delegates_to(self):
        self.assertTrue(callable(pipeline.load_source_diagnostics))
        self.assertTrue(callable(pipeline.summarize_notable_diagnostics))


if __name__ == "__main__":
    unittest.main()
