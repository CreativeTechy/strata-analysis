import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitor_discovery


class DiscoverCompetitorsTests(unittest.TestCase):
    """discover_competitors() does a deferred `from
    services.competitors.business_profile_store import profile_context`
    import inside the function body, not at module level - a bad import path
    there only breaks at call time, so this must actually invoke the
    function (not just import the module) to catch it. Regression test for a
    reorg that broke exactly this: the module-level import graph checked out
    fine while this deferred import still pointed at the pre-move module
    path."""

    def test_returns_early_without_a_business_profile(self):
        result = competitor_discovery.discover_competitors({})
        self.assertEqual(result, {
            "competitors": [],
            "rejected": [],
            "error": "No business profile to compare against.",
        })


if __name__ == "__main__":
    unittest.main()
