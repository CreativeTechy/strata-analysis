import os
import unittest
from unittest.mock import ANY, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class AnalysisRoutesTestCase(unittest.TestCase):
    """Route-wiring/response-shape tests for the analysis-pipeline HTTP
    layer. Auth/permission/CSRF machinery is bypassed via dependency
    overrides + patches (covered separately by auth's own tests, if any) so
    these focus purely on: does the route call the right repository
    function, and does it shape 404s/skips/pagination correctly."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._csrf_patcher = patch("services.auth.auth._enforce_csrf")
        cls._csrf_patcher.start()
        cls._perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"pipeline.run", "pipeline.view", "articles.view", "projects.update"},
        )
        cls._perm_patcher.start()
        # _ensure_project_visible() short-circuits on full_access without a
        # DB round trip - fake admin is full_access, same as user_permission_keys above.
        cls._full_access_patcher = patch("services.auth.permissions_store.user_is_full_access", return_value=True)
        cls._full_access_patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        cls._csrf_patcher.stop()
        cls._perm_patcher.stop()
        cls._full_access_patcher.stop()


class AnalyzeSingleArticleTests(AnalysisRoutesTestCase):
    def test_404_when_article_does_not_exist(self):
        with patch("main.load_article_for_reanalysis", return_value=None):
            resp = self.client.post("/api/articles/999/analyze")
        self.assertEqual(resp.status_code, 404)

    def test_skips_already_successful_analysis_without_force(self):
        current = {"analysis_status": "success", "summary": "ok"}
        with patch("main.load_article_for_reanalysis", return_value={"id": 1}), \
             patch("main.get_article_analysis", return_value=current), \
             patch("main.reanalyze_article") as mock_reanalyze:
            resp = self.client.post("/api/articles/1/analyze")
        body = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["status"], "skipped")
        self.assertEqual(body["analysis"], current)
        mock_reanalyze.assert_not_called()

    def test_force_reruns_even_if_already_successful(self):
        current = {"analysis_status": "success"}
        with patch("main.load_article_for_reanalysis", return_value={"id": 1}), \
             patch("main.get_article_analysis", return_value=current), \
             patch("main.mark_processing") as mock_mark, \
             patch("main.reanalyze_article") as mock_reanalyze:
            resp = self.client.post("/api/articles/1/analyze", json={"force": True})
        self.assertEqual(resp.json()["status"], "processing")
        mock_mark.assert_called_once_with(1)
        mock_reanalyze.assert_called_once_with(1)

    def test_queues_analysis_for_a_not_yet_successful_article(self):
        with patch("main.load_article_for_reanalysis", return_value={"id": 1}), \
             patch("main.get_article_analysis", return_value={"analysis_status": "failed"}), \
             patch("main.mark_processing") as mock_mark, \
             patch("main.reanalyze_article") as mock_reanalyze:
            resp = self.client.post("/api/articles/1/analyze")
        self.assertEqual(resp.json(), {"article_id": 1, "status": "processing"})
        mock_mark.assert_called_once_with(1)
        mock_reanalyze.assert_called_once_with(1)


class AnalyzeBatchTests(AnalysisRoutesTestCase):
    def test_empty_article_ids_is_a_400(self):
        resp = self.client.post("/api/articles/analyze", json={"article_ids": []})
        self.assertEqual(resp.status_code, 400)

    def test_too_many_article_ids_is_a_400(self):
        resp = self.client.post("/api/articles/analyze", json={"article_ids": list(range(main.MAX_BATCH_ANALYZE_IDS + 1))})
        self.assertEqual(resp.status_code, 400)

    def test_splits_into_queued_skipped_and_not_found(self):
        def fake_load(article_id):
            return None if article_id == 3 else {"id": article_id}

        def fake_analysis(article_id):
            return {"analysis_status": "success"} if article_id == 2 else {"analysis_status": "failed"}

        with patch("main.load_article_for_reanalysis", side_effect=fake_load), \
             patch("main.get_article_analysis", side_effect=fake_analysis), \
             patch("main.mark_processing"), \
             patch("main.reanalyze_articles") as mock_batch:
            resp = self.client.post("/api/articles/analyze", json={"article_ids": [1, 2, 3]})
        body = resp.json()
        self.assertEqual(body["queued"], [1])
        self.assertEqual(body["skipped"], [2])
        self.assertEqual(body["not_found"], [3])
        mock_batch.assert_called_once_with([1])


class ReprocessArticleTests(AnalysisRoutesTestCase):
    def test_404_when_article_does_not_exist(self):
        with patch("main.load_article_for_reanalysis", return_value=None):
            resp = self.client.post("/api/articles/999/reprocess")
        self.assertEqual(resp.status_code, 404)

    def test_always_forces_a_run_and_stamps_reprocess_requested_at(self):
        with patch("main.load_article_for_reanalysis", return_value={"id": 1}), \
             patch("main.mark_reprocess_requested", return_value="2026-01-01T00:00:00+00:00") as mock_mark, \
             patch("main.reanalyze_article") as mock_reanalyze:
            resp = self.client.post("/api/articles/1/reprocess")
        body = resp.json()
        self.assertEqual(body["status"], "processing")
        self.assertEqual(body["reprocess_requested_at"], "2026-01-01T00:00:00+00:00")
        mock_mark.assert_called_once_with(1)
        mock_reanalyze.assert_called_once_with(1)


class GetArticleAnalysisTests(AnalysisRoutesTestCase):
    def test_404_when_article_not_found(self):
        with patch("main.get_article_analysis", return_value=None):
            resp = self.client.get("/api/articles/999/analysis")
        self.assertEqual(resp.status_code, 404)

    def test_returns_wrapped_analysis(self):
        analysis = {"article_id": 1, "analysis_status": "success"}
        with patch("main.get_article_analysis", return_value=analysis):
            resp = self.client.get("/api/articles/1/analysis")
        self.assertEqual(resp.json(), {"analysis": analysis})


class AnalysisStatusTests(AnalysisRoutesTestCase):
    def test_returns_counts_and_total(self):
        with patch("main.get_analysis_status_counts", return_value={"success": 5, "failed": 2}):
            resp = self.client.get("/api/analysis/status")
        self.assertEqual(resp.json(), {"project_id": None, "counts": {"success": 5, "failed": 2}, "total": 7})


class AnalysisErrorsTests(AnalysisRoutesTestCase):
    def test_returns_paginated_errors(self):
        page = {"errors": [{"id": 1, "analysis_error": "model_unavailable"}], "total": 1, "limit": 24, "offset": 0}
        with patch("main.list_analysis_errors", return_value=page) as mock_list:
            resp = self.client.get("/api/articles/analysis-errors?limit=10&offset=5")
        self.assertEqual(resp.json(), page)
        mock_list.assert_called_once_with(project_id=None, limit=10, offset=5)


class ProjectIdeaClustersTests(AnalysisRoutesTestCase):
    def test_404_when_project_not_found(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.get("/api/projects/1/idea-clusters")
        self.assertEqual(resp.status_code, 404)

    def test_returns_clusters_page(self):
        page = {"clusters": [{"idea": "charging is slow"}], "total": 1, "limit": 50, "offset": 0}
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_clusters_for_project", return_value=page):
            resp = self.client.get("/api/projects/1/idea-clusters")
        self.assertEqual(resp.json(), page)

    def test_404_when_cluster_not_found_in_project(self):
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_articles_for_idea_cluster", return_value=None):
            resp = self.client.get("/api/projects/1/idea-clusters/5/articles")
        self.assertEqual(resp.status_code, 404)

    def test_returns_cluster_articles_page(self):
        page = {"articles": [{"id": 10, "title": "EV Review"}], "total": 1, "limit": 10, "offset": 0}
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_articles_for_idea_cluster", return_value=page):
            resp = self.client.get("/api/projects/1/idea-clusters/5/articles")
        self.assertEqual(resp.json(), page)


class ProjectIdeaComparisonsTests(AnalysisRoutesTestCase):
    """get_project_idea_comparisons_view()'s cache-unless-asked shape: a plain
    GET reads whatever is cached; `regenerate=true` always resynthesizes; a
    `run_id` scope generates lazily the first time it's viewed, gated on
    has_run_generation_attempt rather than "nothing cached yet" (a run whose
    articles genuinely have fewer than two cross-source ideas caches as zero
    rows too - see services/articles/idea_comparisons.py)."""

    def test_404_when_project_not_found(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.get("/api/projects/1/idea-comparisons")
        self.assertEqual(resp.status_code, 404)

    def test_plain_get_returns_cached_comparisons_without_regenerating(self):
        cached = [{"idea_cluster_id": 1, "idea": "petrol price"}]
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_comparisons", return_value=cached), \
             patch("main.generate_idea_comparisons") as mock_generate:
            resp = self.client.get("/api/projects/1/idea-comparisons")
        self.assertEqual(resp.json(), {"comparisons": cached})
        mock_generate.assert_not_called()

    def test_regenerate_flag_always_resynthesizes_project_wide(self):
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_comparisons", return_value=[]), \
             patch("main.generate_idea_comparisons") as mock_generate:
            resp = self.client.get("/api/projects/1/idea-comparisons?regenerate=true")
        self.assertEqual(resp.status_code, 200)
        mock_generate.assert_called_once_with(1, run_id=None)

    def test_run_scoped_first_view_generates_when_never_attempted(self):
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_comparisons", return_value=[]), \
             patch("main.has_run_generation_attempt", return_value=False), \
             patch("main.generate_idea_comparisons") as mock_generate:
            resp = self.client.get("/api/projects/1/idea-comparisons?run_id=run-123")
        self.assertEqual(resp.status_code, 200)
        mock_generate.assert_called_once_with(1, run_id="run-123")

    def test_run_scoped_repeat_view_does_not_regenerate_once_attempted(self):
        """The regression this covers: before has_run_generation_attempt, a
        run with zero qualifying cross-source ideas cached as an empty list
        indistinguishable from "never generated", so every view re-triggered
        generate_idea_comparisons (and, during a provider outage, re-failed)
        instead of caching that outcome after the first attempt."""
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_comparisons", return_value=[]), \
             patch("main.has_run_generation_attempt", return_value=True), \
             patch("main.generate_idea_comparisons") as mock_generate:
            resp = self.client.get("/api/projects/1/idea-comparisons?run_id=run-123")
        self.assertEqual(resp.json(), {"comparisons": []})
        mock_generate.assert_not_called()

    def test_llm_error_during_lazy_run_scoped_generation_is_a_soft_error(self):
        from llm_client import LLMConnectionError

        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_idea_comparisons", return_value=[]), \
             patch("main.has_run_generation_attempt", return_value=False), \
             patch("main.generate_idea_comparisons", side_effect=LLMConnectionError("down")):
            resp = self.client.get("/api/projects/1/idea-comparisons?run_id=run-123")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["comparisons"], [])
        self.assertEqual(body["error_code"], "llm_connection_error")

    def test_detail_returns_comparison_with_facts(self):
        comparison = {"idea_cluster_id": 7, "facts": [{"id": 2}], "summary_stale": True}
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.get_idea_comparison", return_value=comparison) as mock_get:
            resp = self.client.get("/api/projects/1/idea-comparisons/7?run_id=run-123")
        self.assertEqual(resp.json(), {"comparison": comparison})
        mock_get.assert_called_once_with(1, 7, run_id="run-123")

    def test_add_fact_returns_saved_fact(self):
        fact = {"id": 9, "fact_text": "Audited sales rose 12%."}
        with patch("main.create_comparison_fact", return_value=fact) as mock_create:
            resp = self.client.post("/api/projects/1/idea-comparisons/7/facts", json={"fact_text": fact["fact_text"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"fact": fact})
        mock_create.assert_called_once_with(1, 7, {"fact_text": fact["fact_text"]}, FAKE_USER)

    def test_regenerate_one_comparison_returns_new_detail(self):
        comparison = {"idea_cluster_id": 7, "summary": "Updated."}
        with patch("main.regenerate_idea_comparison", return_value=comparison) as mock_regenerate:
            resp = self.client.post("/api/projects/1/idea-comparisons/7/regenerate?run_id=run-123")
        self.assertEqual(resp.json(), {"comparison": comparison})
        mock_regenerate.assert_called_once_with(1, 7, run_id="run-123")


class ProjectSourcesTests(AnalysisRoutesTestCase):
    def test_404_when_project_not_found(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.get("/api/projects/1/sources")
        self.assertEqual(resp.status_code, 404)

    def test_returns_wrapped_sources(self):
        page = {
            "sources": [{"key": "real:nytimes.com", "type": "real", "label": "nytimes.com", "article_count": 2}],
            "total": 1,
            "limit": 20,
            "offset": 0,
        }
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_project_sources", return_value=page) as mock_list:
            resp = self.client.get("/api/projects/1/sources")
        self.assertEqual(resp.json(), page)
        mock_list.assert_called_once_with(1, limit=20, offset=0)

    def test_passes_through_limit_and_offset(self):
        page = {"sources": [], "total": 0, "limit": 5, "offset": 10}
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_project_sources", return_value=page) as mock_list:
            resp = self.client.get("/api/projects/1/sources?limit=5&offset=10")
        self.assertEqual(resp.json(), page)
        mock_list.assert_called_once_with(1, limit=5, offset=10)


class SetProjectSourceTrustRouteTests(AnalysisRoutesTestCase):
    """Writing a trust tier needs projects.update (same permission
    provenance-review already uses for a project-scoped write), not the
    read-only articles.view the rest of this module's fixture grants."""

    KNOWN = {"real:reuters.com": {"type": "real", "label": "reuters.com"}}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._trust_perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"pipeline.run", "pipeline.view", "articles.view", "projects.update"},
        )
        cls._trust_perm_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._trust_perm_patcher.stop()
        super().tearDownClass()

    def test_404_when_project_not_found(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.post("/api/projects/1/sources/trust", json={"key": "real:reuters.com"})
        self.assertEqual(resp.status_code, 404)

    def test_404_when_key_is_not_one_of_this_projects_sources(self):
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_project_source_keys", return_value=self.KNOWN):
            resp = self.client.post(
                "/api/projects/1/sources/trust",
                json={"key": "real:some-other-host.example", "tier": "trusted", "reason": "why"},
            )
        self.assertEqual(resp.status_code, 404)

    def test_400_on_an_invalid_tier(self):
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_project_source_keys", return_value=self.KNOWN), \
             patch("main.set_source_trust_tier", side_effect=ValueError("Invalid trust tier: 'bogus'")):
            resp = self.client.post(
                "/api/projects/1/sources/trust",
                json={"key": "real:reuters.com", "tier": "bogus", "reason": "why"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_sets_the_tier_and_returns_the_shared_trust_shape(self):
        row = {
            "source_key": "real:reuters.com", "source_type": "real", "tier": "trusted",
            "reason": "Wire service.", "set_by_name": "alice", "updated_at": "2026-01-01T00:00:00Z",
        }
        with patch("main.get_project", return_value={"id": 1}), \
             patch("main.list_project_source_keys", return_value=self.KNOWN), \
             patch("main.set_source_trust_tier", return_value=row) as mock_set:
            resp = self.client.post(
                "/api/projects/1/sources/trust",
                json={"key": "real:reuters.com", "tier": "trusted", "reason": "Wire service."},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            "tier": "trusted", "reason": "Wire service.", "set_by": "alice",
            "updated_at": "2026-01-01T00:00:00Z", "is_default": False,
        })
        # The source's own type is looked up rather than trusted blindly from
        # the request body when the caller doesn't pass one.
        mock_set.assert_called_once_with("real:reuters.com", "real", "trusted", "Wire service.", ANY, project_id=1)


class DeleteArticlesRouteTests(AnalysisRoutesTestCase):
    """delete_articles() does a deferred `from services.articles.store
    import delete_all_articles` import inside the route body, not at module
    level, so `main.delete_all_articles` never exists to patch the way other
    routes' module-level imports do - a bad import path here only breaks at
    call time. Regression test for a reorg that broke exactly this: the
    module-level import graph checked out fine while this deferred import
    still pointed at the pre-move module path."""

    CONFIRM = "/api/articles?confirm=DELETE%20ALL%20ARTICLES"

    def test_deletes_all_articles_for_an_admin_with_the_confirmation_phrase(self):
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch(
            "services.articles.store.delete_all_articles", return_value=7
        ) as mock_delete:
            resp = self.client.delete(self.CONFIRM)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, "deleted": 7})
        mock_delete.assert_called_once_with(actor="admin")

    def test_refuses_without_the_confirmation_phrase(self):
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch("services.articles.store.delete_all_articles") as mock_delete:
            resp = self.client.delete("/api/articles")
            wrong = self.client.delete("/api/articles?confirm=yes")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(wrong.status_code, 400)
        mock_delete.assert_not_called()

    def test_refuses_a_non_admin_even_with_articles_delete(self):
        """articles.delete alone covers one project's articles (see
        RemoveProjectArticlesRouteTests); wiping every project is admin-only."""
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch(
            "services.auth.permissions_store.user_is_full_access", return_value=False
        ), patch("services.articles.store.delete_all_articles") as mock_delete:
            resp = self.client.delete(self.CONFIRM)
        self.assertEqual(resp.status_code, 403)
        mock_delete.assert_not_called()

    def test_reports_a_503_when_the_store_fails(self):
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch(
            "services.articles.store.delete_all_articles", return_value=None
        ):
            resp = self.client.delete(self.CONFIRM)
        self.assertEqual(resp.status_code, 503)

    def test_deletes_one_article(self):
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch(
            "services.articles.store.delete_article", return_value=True
        ) as mock_delete:
            resp = self.client.delete("/api/articles/42")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})
        mock_delete.assert_called_once_with(42)

    def test_404s_when_article_not_found(self):
        with patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.delete"},
        ), patch(
            "services.articles.store.delete_article", return_value=False
        ):
            resp = self.client.delete("/api/articles/999")
        self.assertEqual(resp.status_code, 404)


class RemoveProjectArticlesRouteTests(AnalysisRoutesTestCase):
    """Removing one project's articles: needs articles.delete, visibility of
    that project, its exact name as confirmation, and no in-flight run."""

    PROJECT = {"id": 1, "name": "UK Oil Evidence"}
    RESULT = {
        "project_id": 1, "articles_removed": 37, "articles_deleted": 30,
        "articles_kept_in_other_projects": 7, "candidates_rejected": 30,
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._delete_perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.view", "articles.delete"},
        )
        cls._delete_perm_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._delete_perm_patcher.stop()
        super().tearDownClass()

    def _remove(self, confirm):
        return self.client.request("DELETE", "/api/projects/1/articles", json={"confirm": confirm})

    def test_removes_with_the_exact_project_name(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_active_run_for_project", return_value=None), \
             patch("services.articles.store.remove_project_articles", return_value=self.RESULT) as mock_remove:
            resp = self._remove("  UK Oil Evidence ")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True, **self.RESULT})
        mock_remove.assert_called_once_with(1, actor="admin")

    def test_refuses_a_wrong_or_empty_confirmation(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_active_run_for_project", return_value=None), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            wrong = self._remove("uk oil evidence")
            empty = self._remove("")
            missing = self.client.delete("/api/projects/1/articles")
        self.assertEqual([wrong.status_code, empty.status_code, missing.status_code], [400, 400, 400])
        mock_remove.assert_not_called()

    def test_an_unnamed_project_cannot_be_confirmed_with_an_empty_string(self):
        with patch("main.get_project", return_value={"id": 1, "name": ""}), \
             patch("main.get_active_run_for_project", return_value=None), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            resp = self._remove("")
        self.assertEqual(resp.status_code, 400)
        mock_remove.assert_not_called()

    def test_refuses_while_an_analysis_run_is_in_flight(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_active_run_for_project", return_value={"id": "run-1", "status": "running"}), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            resp = self._remove("UK Oil Evidence")
        self.assertEqual(resp.status_code, 409)
        mock_remove.assert_not_called()

    def test_404_for_an_unknown_project(self):
        with patch("main.get_project", return_value=None), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            resp = self._remove("anything")
        self.assertEqual(resp.status_code, 404)
        mock_remove.assert_not_called()

    def test_404_for_a_project_the_user_is_not_linked_to(self):
        with patch("services.auth.permissions_store.user_is_full_access", return_value=False), \
             patch("services.auth.authz.list_project_ids_for_user", return_value=[2]), \
             patch("main.get_project", return_value=self.PROJECT), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            resp = self._remove("UK Oil Evidence")
        self.assertEqual(resp.status_code, 404)
        mock_remove.assert_not_called()

    def test_403_without_articles_delete(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}), \
             patch("services.articles.store.remove_project_articles") as mock_remove:
            resp = self._remove("UK Oil Evidence")
        self.assertEqual(resp.status_code, 403)
        mock_remove.assert_not_called()

    def test_503_when_the_store_fails(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_active_run_for_project", return_value=None), \
             patch("services.articles.store.remove_project_articles", return_value=None):
            resp = self._remove("UK Oil Evidence")
        self.assertEqual(resp.status_code, 503)

    def test_preview_returns_counts_and_the_active_run(self):
        counts = {"linked_articles": 37, "only_in_project": 30, "shared_with_other_projects": 7}
        run = {"id": "run-1", "status": "running", "articles_selected": 25, "articles_analyzed": 12, "error": None}
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_active_run_for_project", return_value=run), \
             patch("services.articles.store.preview_project_article_removal", return_value=counts):
            resp = self.client.get("/api/projects/1/articles/removal-preview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {
            "project": {"id": 1, "name": "UK Oil Evidence"},
            **counts,
            "active_run": {"id": "run-1", "status": "running", "articles_selected": 25, "articles_analyzed": 12},
        })

    def test_preview_404_for_an_unknown_project(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.get("/api/projects/1/articles/removal-preview")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
