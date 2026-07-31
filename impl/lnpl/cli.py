"""`python3 -m lnpl` — compile and run LNPL sources.

    lnpl compile <src.lnpl> [-o out.lir.json]   parse + lower, emit IR
    lnpl run <src.lnpl> [--payload file.json]   compile then execute (mode A)
"""

import argparse
import json
import os
import sys

from .interp import Interpreter, RunError
from .lexer import LexError
from .lower import LowerError, lower
from .parser import ParseError, parse

DEFAULT_PAYLOAD = {
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "email": "user@example.com",
    "password": "s3cret-value",
    "createdAt": "2026-07-31T09:00:00Z",
}


def compile_source(path):
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    module_name = os.path.splitext(os.path.basename(path))[0]
    return lower(parse(source), module_name).to_document()


def _dump(document):
    """2-space pretty JSON — the storage form (RFC-0001 Appendix A)."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def cmd_compile(args):
    doc = compile_source(args.source)
    text = _dump(doc)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d nodes)" % (args.output, len(doc["nodes"])))
    else:
        sys.stdout.write(text)
    return 0


def cmd_run(args):
    doc = compile_source(args.source)
    payload = DEFAULT_PAYLOAD
    if args.payload:
        with open(args.payload, encoding="utf-8") as fh:
            payload = json.load(fh)

    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to run", file=sys.stderr)
        return 1
    target = args.workflow or workflows[0]["id"]

    rows = {}
    if not args.no_row:
        for n in doc["nodes"]:
            if n["kind"] == "Entity":
                rows[n["id"]] = dict(payload)
    interp = Interpreter(doc, repo_rows=rows)
    result = interp.run_workflow(target, payload)

    if args.json:
        sys.stdout.write(_dump({"result": result, "trace": interp.trace.to_dict()}))
    else:
        _print_human(result, interp)
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

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (LexError, ParseError, LowerError) as exc:
        print("compile error: %s" % exc, file=sys.stderr)
        return 2
    except RunError as exc:
        print("runtime error: %s" % exc, file=sys.stderr)
        return 3
