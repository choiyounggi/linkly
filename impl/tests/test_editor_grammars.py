"""Editor grammars generated from `impl/lnpl/grammar.py` (issue #254).

Pins the tree-sitter grammar, its highlight query and the TextMate grammar:
every closed-vocabulary token is covered (checked against the raw compiler
tables, imported independently of grammar.py), no token lands in two classes,
and the head-only classes (verbs, spec expectations) match only at a line head.

`TreeSitterCliTest` builds and runs the grammar with the real tree-sitter CLI,
which needs node; CI has neither, so that class skips there and runs locally.
The VS Code manifest is pinned here too, with the exact argv the extension
spawns run as a real process.
"""
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from lnpl.grammar import (_EDITOR_SCOPES, _RULES, _highlight_classes,
                          render_textmate, render_tree_sitter,
                          render_tree_sitter_highlights)
from lnpl.lexer import (ARITH_OPS, COMPARATORS, KEYWORDS_CLAUSE,
                        KEYWORDS_CONTROL, KEYWORDS_TOP, LOGICAL_OPS)
from lnpl.lower import PERF_METRICS, POLICY_NAMES, SECURITY_MECHANISMS, VERB_LEXICON
from lnpl.spec import EXPECTATIONS
from lnpl.types import SEMANTIC_TYPES
from lnpl.vocab import vocabulary_document
from tests.test_lsp import EXIT, INIT_LITERAL, SHUTDOWN, frame, read_frames

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")
VSCODE = os.path.join(REPO, "editors", "vscode")

RAW_MEMBERS = (set(VERB_LEXICON) | set(KEYWORDS_TOP) | set(KEYWORDS_CLAUSE)
               | set(KEYWORDS_CONTROL) | set(SEMANTIC_TYPES) | set(COMPARATORS)
               | set(ARITH_OPS) | set(LOGICAL_OPS) | set(POLICY_NAMES)
               | set(SECURITY_MECHANISMS) | set(PERF_METRICS) | set(EXPECTATIONS))


def _class_tokens(name):
    return dict(_highlight_classes(vocabulary_document()))[name]


def _textmate_verb_pattern():
    doc = json.loads(render_textmate())
    scope = _EDITOR_SCOPES["verb"][0]
    matches = [p for p in doc["patterns"]
               if p.get("captures", {}).get("1", {}).get("name") == scope]
    if len(matches) != 1:
        raise AssertionError("expected one verb pattern, got %r" % matches)
    return matches[0]["match"]


class EditorGrammarRenderTest(unittest.TestCase):
    def test_scopes_cover_exactly_the_rules(self):
        self.assertEqual(set(_EDITOR_SCOPES),
                         {name for name, _, _ in _RULES} - {"spec_given_form"})

    def test_classes_cover_every_raw_table_member(self):
        tokens = set()
        for _name, members in _highlight_classes(vocabulary_document()):
            tokens |= set(members)
        self.assertEqual(tokens, RAW_MEMBERS)

    def test_no_token_is_in_two_classes(self):
        seen = {}
        for name, members in _highlight_classes(vocabulary_document()):
            for token in members:
                self.assertNotIn(token, seen, "%r in %s and %s" % (token, seen.get(token), name))
                seen[token] = name
        self.assertTrue(seen)

    def test_overlaps_resolve_to_the_first_rule(self):
        self.assertIn("cache", _class_tokens("verb"))
        self.assertIn("when", _class_tokens("clause_keyword"))
        self.assertIn("parallel", _class_tokens("control_keyword"))
        self.assertNotIn("cache", _class_tokens("performance_clause"))

    def test_tree_sitter_text_names_lnpl_and_every_verb(self):
        text = render_tree_sitter()
        lines = text.split("\n")
        self.assertIn("generated — do not hand-edit", lines[0])
        self.assertIn("name: 'lnpl'", text)
        verb_lines = [line for line in lines if line.strip().startswith("verb: $ =>")]
        self.assertEqual(len(verb_lines), 1)
        for verb in VERB_LEXICON:
            self.assertIn(json.dumps(verb), verb_lines[0])

    def test_tree_sitter_arg_rule_excludes_head_only_classes(self):
        lines = render_tree_sitter().split("\n")
        arg = [line for line in lines if line.strip().startswith("_arg: $ =>")]
        head = [line for line in lines if line.strip().startswith("_head: $ =>")]
        self.assertEqual(len(arg), 1)
        self.assertNotIn("$.verb", arg[0])
        self.assertNotIn("$.spec_expect", arg[0])
        self.assertIn("$.verb", head[0])
        self.assertIn("$.spec_expect", head[0])

    def test_single_token_class_is_a_bare_string(self):
        self.assertIn('    logical_op: $ => "and",\n', render_tree_sitter())

    def test_highlights_capture_only_rules_that_exist(self):
        grammar = render_tree_sitter()
        query = render_tree_sitter_highlights()
        names = re.findall(r"^\((\w+)\) @\w+$", query, re.MULTILINE)
        self.assertIn("comment", names)
        self.assertEqual(len(names), len(_EDITOR_SCOPES) + 1)
        for name in names:
            self.assertIn("%s: $ =>" % name, grammar)

    def test_textmate_is_sorted_json_with_scope_name(self):
        text = render_textmate()
        doc = json.loads(text)
        self.assertEqual(doc["scopeName"], "source.lnpl")
        self.assertIs(doc["_generated"]["hand_edit"], False)
        self.assertEqual(text, json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n")

    def test_textmate_verb_pattern_lists_every_verb_and_compiles(self):
        for pattern in json.loads(render_textmate())["patterns"]:
            re.compile(pattern["match"])
        group = re.search(r"\((.*)\)\(\?!", _textmate_verb_pattern()).group(1)
        self.assertEqual(set(group.split("|")), set(VERB_LEXICON))

    def test_textmate_verb_pattern_matches_a_step_head_only(self):
        verb = re.compile(_textmate_verb_pattern())
        self.assertEqual(verb.findall("    create note"), ["create"])
        self.assertEqual(verb.match("    create note").span(1), (4, 10))
        self.assertIsNone(verb.search("    input.create x"))
        self.assertIsNone(verb.search("    entity create"))

    def test_empty_vocabulary_classes_are_skipped(self):
        # boundary: a class with no tokens yields no rule and no reference
        vocab = copy.deepcopy(vocabulary_document())
        vocab["verbs"] = {}
        text = render_tree_sitter(vocab)
        self.assertNotIn("    verb: $ =>", text)
        self.assertNotIn("$.verb", text)
        self.assertNotIn("verb", dict(_highlight_classes(vocab)))
        self.assertNotIn("(verb)", render_tree_sitter_highlights(vocab))


@unittest.skipUnless(shutil.which("tree-sitter") and shutil.which("node"),
                     "tree-sitter CLI and node are local-only (CI has neither)")
class TreeSitterCliTest(unittest.TestCase):
    def setUp(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, self.tmp)
        with open(os.path.join(self.tmp, "grammar.js"), "w", encoding="utf-8") as fh:
            fh.write(render_tree_sitter())
        os.makedirs(os.path.join(self.tmp, "queries"))
        with open(os.path.join(self.tmp, "queries", "highlights.scm"), "w", encoding="utf-8") as fh:
            fh.write(render_tree_sitter_highlights())
        libdir = os.path.join(self.tmp, "lib")
        os.makedirs(libdir)
        self.env = dict(os.environ, TREE_SITTER_LIBDIR=libdir)
        proc = self.run_ts("generate")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def run_ts(self, *args):
        return subprocess.run(["tree-sitter", *args], cwd=self.tmp, env=self.env,
                              capture_output=True, text=True, timeout=300)

    def test_examples_parse_without_errors(self):
        examples = sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl")))
        self.assertEqual(len(examples), 7)
        proc = self.run_ts("parse", "--quiet", "--stat", *examples)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("failed parses: 0", proc.stdout.lower())

    def test_a_tab_is_a_parse_error(self):
        bad = os.path.join(self.tmp, "bad.lnpl")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("workflow X\n\tcreate a\n")
        proc = self.run_ts("parse", bad)
        self.assertNotEqual(proc.returncode, 0)

    def test_highlight_query_compiles_against_the_grammar(self):
        proc = self.run_ts("query", "queries/highlights.scm",
                           os.path.join(REPO, "examples", "login.lnpl"))
        self.assertEqual(proc.returncode, 0, proc.stderr)


def _extension_args():
    with open(os.path.join(VSCODE, "extension.js"), encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"args:\s*(\[[^\]]*\])", text)
    if m is None:
        raise AssertionError("extension.js has no `args: [...]`")
    return json.loads(m.group(1)), text


def _run_module(args):
    return subprocess.run([sys.executable, "-m", "lnpl", *args],
                          input=frame(INIT_LITERAL) + frame(SHUTDOWN) + frame(EXIT),
                          capture_output=True, timeout=30, cwd=REPO,
                          env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "impl")))


class VsCodeSkeletonTest(unittest.TestCase):
    def test_manifest_contributes_the_language_and_grammar(self):
        with open(os.path.join(VSCODE, "package.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
        language = manifest["contributes"]["languages"][0]
        self.assertEqual(language["id"], "lnpl")
        self.assertEqual(language["extensions"], [".lnpl"])
        self.assertEqual(manifest["activationEvents"], ["onLanguage:lnpl"])
        self.assertEqual(manifest["main"], "./extension.js")
        self.assertTrue(os.path.isfile(os.path.join(VSCODE, manifest["main"])))
        grammar = manifest["contributes"]["grammars"][0]
        self.assertEqual(grammar["language"], "lnpl")
        self.assertEqual(grammar["scopeName"], json.loads(render_textmate())["scopeName"])
        self.assertTrue(os.path.isfile(os.path.join(VSCODE, grammar["path"])))
        self.assertEqual(manifest["dependencies"], {"vscode-languageclient": "9.0.1"})

    def test_no_lockfile_or_node_modules(self):
        # boundary: the skeleton ships no install artefacts
        for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "node_modules"):
            self.assertFalse(os.path.exists(os.path.join(VSCODE, name)), name)

    def test_extension_spawns_lsp_without_transport(self):
        args, text = _extension_args()
        self.assertEqual(args, ["lsp"])
        # The comment explaining the omission names the key; the code must not.
        code = "\n".join(line.split("//", 1)[0] for line in text.splitlines())
        self.assertIn("serverOptions", code)
        self.assertNotIn("transport", code.lower())

    def test_the_exact_client_argv_starts_the_server(self):
        args, _text = _extension_args()
        proc = _run_module(args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("capabilities", read_frames(proc.stdout)[0]["result"])

    def test_stdio_flag_would_be_rejected(self):
        # error case: what TransportKind.stdio would spawn — the reason `transport` is omitted
        args, _text = _extension_args()
        proc = _run_module(args + ["--stdio"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b"unrecognized arguments", proc.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is local-only")
    def test_extension_js_parses(self):
        proc = subprocess.run(["node", "--check", os.path.join(VSCODE, "extension.js")],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
