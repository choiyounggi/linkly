"""`python3 -m lnpl` — compile and run LNPL sources.

    lnpl compile <src.lnpl> [-o out.lir.json]   parse + lower, emit IR
    lnpl run <src.lnpl> [--payload file.json]   compile then execute (mode A)
"""

import argparse
import json
import os
import sys

from .diagnostics import format_lines
from .interp import Interpreter, RunError, refinement_index, sample_payload
from .lexer import LexError
from .lower import LowerError, lower
from .parser import ParseError, parse
from .repo_policy import default_rows
from .backend import BackendError, build as build_native, run_binary


def _parse_fields(specs):
    """Parse repeated --field NAME=VALUE into {name: int}."""
    out = {}
    for spec in specs or []:
        name, sep, raw = spec.partition("=")
        if not sep or not name.strip():
            raise ValueError("--field expects NAME=VALUE, got %r" % spec)
        try:
            out[name.strip()] = int(raw)
        except ValueError:
            raise ValueError("--field %s: value must be an integer, got %r"
                             % (name.strip(), raw))
    return out
from .agents import run_cycle
from .differential import DifferentialError, verify as verify_modes
from .kb import KbError, KnowledgeBase
from .openapi import OpenApiError, generate as generate_openapi
from .spec import SpecError, extract, run_manifest


def _entities(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Entity"]


def compile_source(path):
    return _compile(path)[0]


def _compile(path):
    """Returns (ir_document, decls, module_name, diagnostics)."""
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    module_name = os.path.splitext(os.path.basename(path))[0]
    decls = parse(source)
    module = lower(decls, module_name)
    return module.to_document(), decls, module_name, module.diagnostics


def _dump(document):
    """2-space pretty JSON — the storage form (RFC-0001 Appendix A)."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _emit_diagnostics(diagnostics):
    """Show diagnostics on stderr — the one place any command prints them.

    stderr, not stdout: `compile` without `-o` writes the IR document to stdout,
    and a warning mixed into it would corrupt the artifact. The lines themselves
    come from `diagnostics.format_lines`, so `compile` and `run` cannot drift
    into two different reports of the same fact.
    """
    for line in format_lines(diagnostics):
        print(line, file=sys.stderr)


def cmd_compile(args):
    doc, _, _, diagnostics = _compile(args.source)
    text = _dump(doc)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d nodes)" % (args.output, len(doc["nodes"])))
    else:
        sys.stdout.write(text)
    _emit_diagnostics(diagnostics)
    return 0


def cmd_run(args):
    doc, _, _, diagnostics = _compile(args.source)
    if args.payload:
        with open(args.payload, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = sample_payload(_entities(doc), refinement_index(doc))

    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to run", file=sys.stderr)
        # A module can declare `security jwt` and never run a step; the
        # declaration is unenforced either way, so the report still goes out.
        _emit_diagnostics(diagnostics)
        return 1
    target = args.workflow or workflows[0]["id"]

    rows = _repo_rows(doc, payload, target, empty=args.no_row)
    interp = Interpreter(doc, repo_rows=rows)
    result = interp.run_workflow(target, payload)
    # Compile-time and run-time findings are one report, not two.
    diagnostics.extend(interp.diagnostics)

    if args.json:
        sys.stdout.write(_dump({"result": result, "trace": interp.trace.to_dict()}))
    else:
        _print_human(result, interp)
    _emit_diagnostics(diagnostics)
    return 0 if result["status"] == "completed" else 1


def _print_human(result, interp):
    root = interp.trace.root
    print("workflow %s -> %s  (%sms, correlation_id=%s)"
          % (root.name if root else "?", result["status"],
             result["duration_ms"], result["correlation_id"]))
    if root:
        for span in root.children:
            marks = "".join(
                " [%s %s]" % (c.kind, ", ".join("%s=%s" % kv for kv in c.attrs.items()) or "-")
                for c in span.children)
            print("  step %-16s %3sms attempts=%s%s"
                  % (span.name, span.duration_ms, span.attrs.get("attempts"), marks))
    if "slo_met" in result:
        print("  response SLO %sms: %s (measured, not enforced)"
              % (result["slo_ms"], "met" if result["slo_met"] else "EXCEEDED"))
    if result["failed_step"]:
        print("  failed at: %s" % result["failed_step"])
    for entry in interp.trace.logs:
        if entry["level"] in ("WARN", "ERROR"):
            print("  %-5s %s" % (entry["level"], entry["message"]))


def cmd_spec(args):
    doc, decls, module_name, _ = _compile(args.source)
    manifest = extract(decls, module_name)
    if not manifest["cases"]:
        print("no `spec` block found in %s" % args.source, file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(_dump(manifest))
        print("wrote %s (%d case(s))" % (args.output, len(manifest["cases"])))
        if not args.run:
            return 0
    elif not args.run:
        sys.stdout.write(_dump(manifest))
        return 0

    passed, failed, lines = run_manifest(manifest, doc)
    for line in lines:
        print(line)
    print("spec: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


def cmd_openapi(args):
    doc = compile_source(args.source)
    spec = generate_openapi(doc)
    text = _dump(spec)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d path(s))" % (args.output, len(spec["paths"])))
    else:
        sys.stdout.write(text)
    return 0


def _repo_rows(doc, payload, workflow_id, empty=False):
    if empty:
        return {}
    return default_rows(doc, workflow_id, payload)


def cmd_build(args):
    doc = compile_source(args.source)
    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to build", file=sys.stderr)
        return 1
    target = args.workflow or workflows[0]["id"]
    path = build_native(doc, target, args.workdir)
    print("native binary: %s" % path)
    if args.run:
        try:
            fields = _parse_fields(args.field)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        rc, lines = run_binary(path, skip=args.skip, condition_fields=fields)
        print("\n".join(lines))
        print("exit=%d" % rc)
    return 0


def cmd_diff(args):
    doc = compile_source(args.source)
    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to compare", file=sys.stderr)
        return 1
    target = args.workflow or workflows[0]["id"]
    if args.payload:
        with open(args.payload, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = sample_payload(_entities(doc), refinement_index(doc))
    # One flag, two derivations of it: mode A gets the seed materialised as rows,
    # mode B gets the seed condition itself (issue #35). Both come from
    # `args.no_row`, so they cannot disagree — and `verify` refuses them if they
    # ever do.
    ok, report = verify_modes(doc, target, payload,
                              _repo_rows(doc, payload, target, empty=args.no_row),
                              args.workdir,
                              seeded=frozenset() if args.no_row else None)
    print("\n".join(report))
    return 0 if ok else 1


def cmd_kb(args):
    kb = KnowledgeBase(root=args.root)
    if args.lint:
        problems = kb.lint()
        for p in problems:
            print(p)
        print("kb lint: %s" % ("OK (%d docs)" % len(kb.index()) if not problems
                               else "%d problem(s)" % len(problems)))
        return 0 if not problems else 1
    if args.route:
        ids = kb.route(args.route)
        print("\n".join(ids) if ids else "(no match — the KB has nothing for that)")
        return 0
    if args.load:
        doc = kb.load(args.load)
        print("# %s  (%s, v%s, %s)" % (doc["id"], doc["category"],
                                       doc["version"], doc["status"]))
        print("sources: %s" % ", ".join(doc["sources"]))
        print()
        print(doc["body"])
        return 0
    for doc_id, meta in sorted(kb.index().items()):
        print("%-40s %-14s %s" % (doc_id, meta["category"], meta["triggers"][:60]))
    return 0


def cmd_agents(args):
    doc = compile_source(args.source)
    kb = KnowledgeBase(root=args.root)
    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to run agents against", file=sys.stderr)
        return 1
    wf = workflows[0]
    steps = [doc_node["name"] for doc_node in doc["nodes"]
             if doc_node["kind"] == "WorkflowStep"
             and doc_node["id"] in wf.get("children", [])]
    server, transcript = run_cycle(doc, kb, wf["name"], steps)

    print("agent cycle over %s (%d step(s))" % (wf["name"], len(steps)))
    for rec in transcript:
        line = "  %-16s kb=%-34s" % (rec["step"], rec["doc_id"] or "(none)")
        if rec["proposal_id"]:
            line += " proposal=%s -> %s applied=%s" % (
                rec["proposal_id"], rec.get("review_state"), rec.get("applied"))
        else:
            line += " (nothing proposed)"
        print(line)
    print("IR nodes: %d -> %d | proposals applied: %s"
          % (len(doc["nodes"]), len(server.doc["nodes"]), server.applied or "none"))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(_dump(server.doc))
        print("wrote %s" % args.output)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lnpl", description="compile and run LNPL sources")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="parse and lower to Semantic IR")
    c.add_argument("source")
    c.add_argument("-o", "--output")
    c.set_defaults(func=cmd_compile)

    r = sub.add_parser("run", help="compile then execute (interpreter mode A)")
    r.add_argument("source")
    r.add_argument("--payload", help="JSON file with the workflow input")
    r.add_argument("--workflow", help="workflow node id (default: the first one)")
    r.add_argument("--json", action="store_true", help="emit result and trace as JSON")
    r.add_argument("--no-row", action="store_true",
                   help="start with an empty repository (exercises retry)")
    r.set_defaults(func=cmd_run)

    sp = sub.add_parser("spec", help="extract `spec` blocks as a test manifest")
    sp.add_argument("source")
    sp.add_argument("-o", "--output", help="write the manifest to this path")
    sp.add_argument("--run", action="store_true", help="execute the manifest")
    sp.set_defaults(func=cmd_spec)

    oa = sub.add_parser("openapi", help="generate an OpenAPI 3.1 document from the IR")
    oa.add_argument("source")
    oa.add_argument("-o", "--output")
    oa.set_defaults(func=cmd_openapi)

    bd = sub.add_parser("build", help="compile to a native binary (mode B)")
    bd.add_argument("source")
    bd.add_argument("--workflow")
    bd.add_argument("--workdir", default=".claude/tmp/lnpl-build")
    bd.add_argument("--run", action="store_true")
    bd.add_argument("--field", action="append", metavar="NAME=VALUE", default=[],
                    help="condition field value for a `when`/`until` comparison "
                         "guard, e.g. --field counter=12 (repeatable). Fields the "
                         "workflow does not compare on are ignored; omitted ones "
                         "default to 0.")
    bd.add_argument("--skip", action="store_true",
                    help="set the Presence `when` guard flag so steps guarded by "
                         "an exists/missing check are skipped. Comparison guards "
                         "are driven by --field, not by this flag.")
    bd.set_defaults(func=cmd_build)

    df = sub.add_parser("diff", help="differential check: mode A vs mode B")
    df.add_argument("source")
    df.add_argument("--workflow")
    df.add_argument("--workdir", default=".claude/tmp/lnpl-diff")
    df.add_argument("--payload", help="JSON file with the workflow input")
    df.add_argument("--no-row", action="store_true")
    df.set_defaults(func=cmd_diff)

    kbp = sub.add_parser("kb", help="inspect the knowledge base (RFC-0005)")
    kbp.add_argument("--root", default=None)
    kbp.add_argument("--lint", action="store_true", help="check RFC-0005 conformance")
    kbp.add_argument("--route", metavar="TASK", help="kb.route(task_description)")
    kbp.add_argument("--load", metavar="DOC_ID", help="kb.load(doc_id)")
    kbp.set_defaults(func=cmd_kb)

    ag = sub.add_parser("agents", help="run the RFC-0006 agent cycle over a source")
    ag.add_argument("source")
    ag.add_argument("--root", default=None, help="KB root")
    ag.add_argument("-o", "--output", help="write the resulting IR here")
    ag.set_defaults(func=cmd_agents)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (LexError, ParseError, LowerError, SpecError, OpenApiError,
            KbError) as exc:
        print("compile error: %s" % exc, file=sys.stderr)
        return 2
    except RunError as exc:
        print("runtime error: %s" % exc, file=sys.stderr)
        return 3
    except (BackendError, DifferentialError) as exc:
        print("backend error: %s" % exc, file=sys.stderr)
        return 4
