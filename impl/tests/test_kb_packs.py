"""KB pack layering — issue #137.

An organization can layer its own KB pack on top of the core 26 documents
without forking core, borrowing OPA's multi-bundle "roots" model: a pack
declares the `doc_id` prefix it owns (`pack.toml`), and two packs whose
prefixes overlap fail to load rather than silently merging.

Fixtures build a synthetic core KB root (not the real bundled `kb/`), so these
tests neither depend on nor risk breaking on the content of the real 26
documents — `test_kb.py` already covers the real, unmodified KB and stays
untouched by this task (0-pack regression proof lives there).
"""

import os
import shutil
import tempfile
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import kb as kb_module
from lnpl.kb import (CATEGORIES, KbError, KnowledgeBase,
                     discover_entry_point_packs, resolve_pack_roots)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")

DOC_TEMPLATE = """---
id: {doc_id}
category: {category}
triggers:
  - {trigger}
version: {version}
status: {status}
sources:
  - {source}
---
{body}
"""

GROUP = kb_module.KB_ENTRY_POINT_GROUP


def _tmp_dir(test_case, prefix):
    d = tempfile.mkdtemp(dir=TMP_ROOT, prefix=prefix)
    test_case.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d


def _write_doc(cat_path, doc_id, category, trigger="widget", version="1.0.0",
               status="verified", source="https://example.test/spec",
               body="Body text."):
    with open(os.path.join(cat_path, doc_id + ".md"), "w", encoding="utf-8") as fh:
        fh.write(DOC_TEMPLATE.format(doc_id=doc_id, category=category,
                                      trigger=trigger, version=version,
                                      status=status, source=source, body=body))


def _write_category_index(cat_path, rows):
    """rows: [(doc_id, triggers_text), ...]."""
    lines = ["# index\n", "\n", "| id | load when |\n", "|----|-----------|\n"]
    for doc_id, triggers in rows:
        lines.append("| `%s` | %s |\n" % (doc_id, triggers))
    with open(os.path.join(cat_path, "index.md"), "w", encoding="utf-8") as fh:
        fh.writelines(lines)


def _write_kb_tree(root, docs):
    """docs: {doc_id: {"category_dir", "category", "trigger"?, "version"?,
    "status"?, "body"?}} -> a KB-shaped tree of category dirs under `root`."""
    by_cat = {}
    for doc_id, spec in docs.items():
        by_cat.setdefault(spec["category_dir"], []).append((doc_id, spec))
    for cat_dir, entries in by_cat.items():
        cat_path = os.path.join(root, cat_dir)
        os.makedirs(cat_path, exist_ok=True)
        _write_category_index(
            cat_path, [(doc_id, spec.get("trigger", "widget")) for doc_id, spec in entries])
        for doc_id, spec in entries:
            _write_doc(cat_path, doc_id, spec["category"],
                       trigger=spec.get("trigger", "widget"),
                       version=spec.get("version", "1.0.0"),
                       status=spec.get("status", "verified"),
                       body=spec.get("body", "Body text."))


def make_core_kb(test_case, docs):
    root = _tmp_dir(test_case, "kb-core-")
    with open(os.path.join(root, "INDEX.md"), "w", encoding="utf-8") as fh:
        fh.write("# core index\n")
    _write_kb_tree(root, docs)
    return root


def make_pack(test_case, name, version, doc_id_prefix, categories, docs,
              write_manifest=True):
    root = _tmp_dir(test_case, "kb-pack-%s-" % name)
    if write_manifest:
        lines = ['name = "%s"\n' % name, 'version = "%s"\n' % version,
                 'doc_id_prefix = "%s"\n' % doc_id_prefix]
        if categories:
            lines.append("categories = [%s]\n"
                         % ", ".join('"%s"' % c for c in categories))
        with open(os.path.join(root, "pack.toml"), "w", encoding="utf-8") as fh:
            fh.writelines(lines)
    _write_kb_tree(root, docs)
    return root


# ---- 0 packs: regression -----------------------------------------------

class ZeroPacksTest(unittest.TestCase):
    """`packs=` absent/empty must reproduce pre-#137 behavior byte for byte."""

    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget gadget"},
        })

    def test_packs_none_and_empty_list_are_identical(self):
        kb_none = KnowledgeBase(root=self.core_root, packs=None)
        kb_empty = KnowledgeBase(root=self.core_root, packs=[])
        self.assertEqual(kb_none.index(), kb_empty.index())
        self.assertEqual(kb_none.categories(), kb_empty.categories())

    def test_categories_is_exactly_the_core_twelve(self):
        kb = KnowledgeBase(root=self.core_root)
        self.assertEqual(kb.categories(), tuple(sorted(CATEGORIES)))
        self.assertEqual(len(kb.categories()), 12)

    def test_loaded_doc_carries_no_pack_key(self):
        kb = KnowledgeBase(root=self.core_root)
        doc = kb.load("testing-widget")
        self.assertNotIn("pack", doc)

    def test_core_doc_path_is_relative_to_repo_root_unchanged(self):
        kb = KnowledgeBase(root=self.core_root)
        doc = kb.load("testing-widget")
        expected = os.path.relpath(
            os.path.join(self.core_root, "testing", "testing-widget.md"), REPO)
        self.assertEqual(doc["path"], expected)

    def test_route_load_verify_lint_all_work_with_no_packs(self):
        kb = KnowledgeBase(root=self.core_root)
        self.assertEqual(kb.route("widget gadget"), ["testing-widget"])
        self.assertTrue(kb.verify("testing-widget", "1.0.0"))
        self.assertFalse(kb.verify("testing-widget", "9.9.9"))
        self.assertEqual(kb.lint(), [])

    def test_lint_reports_an_unrecognized_category_as_a_triple(self):
        root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Nonexistent",
                               "trigger": "widget gadget"},
        })
        kb = KnowledgeBase(root=root)
        problems = kb.lint()
        self.assertEqual(len(problems), 1)
        self.assertIn("testing-widget: category 'Nonexistent' is not a "
                      "recognized category (core: %s; registered packs: none)"
                      % ", ".join(CATEGORIES), problems)


# ---- 1 pack --------------------------------------------------------------

class OnePackTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget gadget"},
        })
        self.pack_root = make_pack(self, "acme", "2.0.0", "acme", ["Compliance"], {
            "acme-audit-log": {"category_dir": "compliance", "category": "Compliance",
                               "trigger": "audit log retention", "version": "2.0.0"},
        })
        self.kb = KnowledgeBase(root=self.core_root, packs=[self.pack_root])

    def test_pack_doc_is_routed(self):
        self.assertIn("acme-audit-log", self.kb.route("audit log retention"))

    def test_pack_doc_load_has_pack_key_and_pack_relative_path(self):
        doc = self.kb.load("acme-audit-log")
        self.assertEqual(doc["pack"], "acme")
        self.assertEqual(doc["path"], os.path.join("compliance", "acme-audit-log.md"))
        self.assertNotIn("..", doc["path"].split(os.sep))

    def test_core_doc_is_unaffected_by_the_pack(self):
        doc = self.kb.load("testing-widget")
        self.assertNotIn("pack", doc)
        self.assertEqual(doc["path"], os.path.relpath(
            os.path.join(self.core_root, "testing", "testing-widget.md"), REPO))

    def test_verify_is_an_exact_pinned_match_on_a_pack_doc(self):
        self.assertTrue(self.kb.verify("acme-audit-log", "2.0.0"))
        self.assertFalse(self.kb.verify("acme-audit-log", "1.0.0"))

    def test_categories_includes_the_packs_declared_category(self):
        self.assertIn("Compliance", self.kb.categories())

    def test_lint_accepts_the_pack_and_its_new_category(self):
        self.assertEqual(self.kb.lint(), [])

    def test_lint_lists_the_registered_pack_when_a_category_is_unrecognized(self):
        _write_doc(os.path.join(self.pack_root, "compliance"), "acme-bogus",
                   "Nonexistent", trigger="bogus")
        _write_category_index(os.path.join(self.pack_root, "compliance"),
                              [("acme-audit-log", "audit log retention"),
                               ("acme-bogus", "bogus")])
        kb = KnowledgeBase(root=self.core_root, packs=[self.pack_root])
        problems = kb.lint()
        self.assertIn("acme-bogus: category 'Nonexistent' is not a "
                      "recognized category (core: %s; registered packs: "
                      "acme(acme))" % ", ".join(CATEGORIES), problems)


# ---- 2 packs ---------------------------------------------------------------

class TwoPacksTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget gadget"},
        })
        self.pack_a = make_pack(self, "acme", "1.0.0", "acme", ["Compliance"], {
            "acme-audit-log": {"category_dir": "compliance", "category": "Compliance",
                               "trigger": "audit"},
        })
        self.pack_b = make_pack(self, "beta", "1.0.0", "beta", ["Compliance"], {
            "beta-retention-policy": {"category_dir": "compliance", "category": "Compliance",
                                      "trigger": "retention"},
        })
        self.kb = KnowledgeBase(root=self.core_root, packs=[self.pack_a, self.pack_b])

    def test_both_packs_docs_are_indexed(self):
        ids = set(self.kb.index())
        self.assertIn("acme-audit-log", ids)
        self.assertIn("beta-retention-policy", ids)

    def test_each_loads_with_its_own_pack_name(self):
        self.assertEqual(self.kb.load("acme-audit-log")["pack"], "acme")
        self.assertEqual(self.kb.load("beta-retention-policy")["pack"], "beta")

    def test_lint_is_clean_across_both_packs(self):
        self.assertEqual(self.kb.lint(), [])


# ---- conflict: overlapping doc_id_prefix -> KbError ------------------------

class PrefixConflictTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget"},
        })

    def test_identical_prefixes_raise_at_construction(self):
        a = make_pack(self, "acme-one", "1.0.0", "acme", [], {
            "acme-doc-one": {"category_dir": "cat", "category": "Testing", "trigger": "one"},
        })
        b = make_pack(self, "acme-two", "1.0.0", "acme", [], {
            "acme-doc-two": {"category_dir": "cat", "category": "Testing", "trigger": "two"},
        })
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[a, b])
        message = str(caught.exception)
        self.assertIn("acme-one", message)
        self.assertIn("acme-two", message)

    def test_nested_prefixes_raise(self):
        a = make_pack(self, "acme", "1.0.0", "acme", [], {
            "acme-doc": {"category_dir": "cat", "category": "Testing", "trigger": "one"},
        })
        b = make_pack(self, "acmefin", "1.0.0", "acme-fin", [], {
            "acme-fin-doc": {"category_dir": "cat", "category": "Testing", "trigger": "two"},
        })
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[a, b])
        message = str(caught.exception)
        self.assertIn("acme", message)
        self.assertIn("acmefin", message)

    def test_disjoint_prefixes_do_not_raise(self):
        a = make_pack(self, "acme", "1.0.0", "acme", [], {
            "acme-doc": {"category_dir": "cat", "category": "Testing", "trigger": "one"},
        })
        b = make_pack(self, "beta", "1.0.0", "beta", [], {
            "beta-doc": {"category_dir": "cat", "category": "Testing", "trigger": "two"},
        })
        KnowledgeBase(root=self.core_root, packs=[a, b])  # must not raise


# ---- core id shadowing: core always wins, silently -------------------------

class CoreShadowTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget"},
            "acme-shadow": {"category_dir": "testing", "category": "Testing",
                            "trigger": "core shadow", "body": "Core version."},
        })
        self.pack_root = make_pack(self, "acme", "1.0.0", "acme", ["Compliance"], {
            "acme-shadow": {"category_dir": "compliance", "category": "Compliance",
                            "trigger": "pack shadow",
                            "body": "Pack version -- must never win."},
        })
        self.kb = KnowledgeBase(root=self.core_root, packs=[self.pack_root])

    def test_core_wins_the_id_collision(self):
        doc = self.kb.load("acme-shadow")
        self.assertNotIn("pack", doc)
        self.assertEqual(doc["category"], "Testing")
        self.assertIn("Core version.", doc["body"])

    def test_lint_stays_clean_despite_the_shadow_attempt(self):
        self.assertEqual(self.kb.lint(), [])

    def test_index_carries_only_the_core_entry(self):
        meta = self.kb.index()["acme-shadow"]
        self.assertNotIn("pack", meta)


# ---- boundary: doc_id outside its own pack's prefix -> KbError -------------

class PrefixMismatchTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget"},
        })
        self.pack_root = make_pack(self, "acme", "1.0.0", "acme", ["Compliance"], {
            "notacme-thing": {"category_dir": "compliance", "category": "Compliance",
                              "trigger": "mismatch"},
        })

    def test_a_doc_id_outside_its_own_prefix_raises_on_index(self):
        kb = KnowledgeBase(root=self.core_root, packs=[self.pack_root])
        with self.assertRaises(KbError) as caught:
            kb.index()
        message = str(caught.exception)
        self.assertIn("doc_id_prefix", message)
        self.assertIn("notacme-thing", message)


# ---- boundary: manifest validation -----------------------------------------

class ManifestBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.core_root = make_core_kb(self, {
            "testing-widget": {"category_dir": "testing", "category": "Testing",
                               "trigger": "widget"},
        })

    def test_missing_pack_toml_raises(self):
        pack_root = _tmp_dir(self, "kb-pack-nomanifest-")
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[pack_root])
        self.assertIn("pack.toml", str(caught.exception))

    def test_missing_required_key_raises(self):
        pack_root = _tmp_dir(self, "kb-pack-badmanifest-")
        with open(os.path.join(pack_root, "pack.toml"), "w", encoding="utf-8") as fh:
            fh.write('name = "acme"\ndoc_id_prefix = "acme"\n')  # no version
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[pack_root])
        self.assertIn("version", str(caught.exception))

    def test_reserved_prefix_raises(self):
        pack_root = _tmp_dir(self, "kb-pack-reserved-")
        with open(os.path.join(pack_root, "pack.toml"), "w", encoding="utf-8") as fh:
            fh.write('name = "x"\nversion = "1.0.0"\ndoc_id_prefix = "core"\n')
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[pack_root])
        self.assertIn("reserved", str(caught.exception))

    def test_invalid_prefix_format_raises(self):
        pack_root = _tmp_dir(self, "kb-pack-badformat-")
        with open(os.path.join(pack_root, "pack.toml"), "w", encoding="utf-8") as fh:
            fh.write('name = "x"\nversion = "1.0.0"\ndoc_id_prefix = "Acme"\n')
        with self.assertRaises(KbError):
            KnowledgeBase(root=self.core_root, packs=[pack_root])

    def test_categories_as_a_bare_string_raises_instead_of_iterating_chars(self):
        # A `categories = "Compliance"` typo (missing brackets) must not
        # silently become one-letter categories via `list("Compliance")`.
        pack_root = _tmp_dir(self, "kb-pack-badcategories-")
        with open(os.path.join(pack_root, "pack.toml"), "w", encoding="utf-8") as fh:
            fh.write('name = "x"\nversion = "1.0.0"\ndoc_id_prefix = "acme"\n'
                     'categories = "Compliance"\n')
        with self.assertRaises(KbError) as caught:
            KnowledgeBase(root=self.core_root, packs=[pack_root])
        self.assertIn("categories", str(caught.exception))


# ---- discovery / merge order (D2) ------------------------------------------

def _entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def _registered(*entry_points):
    """A patcher for `kb_module`'s only external discovery call — same
    convention `test_driver_spi.py` uses for `lnpl.drivers`."""
    return mock.patch.object(
        kb_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


class DiscoveryMergeOrderTest(unittest.TestCase):
    """D2: entry-points (name-sorted) -> LNPL_KB_PACKS env -> --kb-pack flag."""

    def test_entry_points_are_discovered_and_name_sorted(self):
        os.environ["LNPL_KB_PACK_FIXTURE_ROOT_ALPHA"] = "/alpha-root"
        os.environ["LNPL_KB_PACK_FIXTURE_ROOT_BETA"] = "/beta-root"
        self.addCleanup(os.environ.pop, "LNPL_KB_PACK_FIXTURE_ROOT_ALPHA", None)
        self.addCleanup(os.environ.pop, "LNPL_KB_PACK_FIXTURE_ROOT_BETA", None)
        zeta = _entry_point("zeta", "tests.kb_pack_spi_fixture:pack_root_beta")
        alpha = _entry_point("alpha", "tests.kb_pack_spi_fixture:pack_root_alpha")
        with _registered(zeta, alpha):  # registered zeta-first, name-sort must reorder
            roots = discover_entry_point_packs()
        self.assertEqual(roots, ["/alpha-root", "/beta-root"])

    def test_merge_order_is_entry_points_then_env_then_flag(self):
        with _registered():
            roots = resolve_pack_roots(flag_packs=["/flag-pack"], env_value="/env-pack")
        self.assertEqual(roots, ["/env-pack", "/flag-pack"])

    def test_zero_entry_points_no_env_no_flag_is_empty(self):
        with _registered():
            self.assertEqual(resolve_pack_roots(), [])

    def test_entry_point_load_failure_becomes_kberror(self):
        broken = _entry_point("broken", "tests.kb_pack_spi_fixture:does_not_exist")
        with _registered(broken):
            with self.assertRaises(KbError):
                discover_entry_point_packs()


if __name__ == "__main__":
    unittest.main()
