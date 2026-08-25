"""`python3 -m lnpl` — compile and run LNPL sources.

    lnpl compile <src.lnpl>... [-o out.lir.json]   parse + lower, emit IR
    lnpl compile <dir>                             *.lnpl in the dir, filename order (#77)
    lnpl run <src.lnpl> [--payload file.json]   compile then execute (mode A)
    lnpl run <src.lnpl> --backend sqlite:s.db   ... against a real store (#25)
    lnpl token <src.lnpl> --path /s/w ...       issue a bearer token (#25)
"""

import argparse
import json
import os
import sys

from . import __version__
from .diagnostics import Diagnostics, SEVERITIES, format_lines, to_records
from .drivers import (DriverError, HmacTokenProvider, TokenError,
                      audience_for_path, open_network, open_repository,
                      _is_url_literal)
from .interp import (Interpreter, RunError, _duration_ms, open_clock,
                     refinement_index, row_shape_mismatches, sample_payload)
from .lexer import LexError
from .lower import LowerError, load_sources, lower
from .parser import ParseError
from .repo_policy import default_rows, row_key
from .backend import (BackendError, build as build_native, condition_field_names,
                      ran_step_indices, restore_skips, run_binary,
                      validation_effect_steps)


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
from .openapi import OpenApiError, _slug, generate as generate_openapi
from .serve import ServeError, build_routes, serve
from .wsgi import (ExporterError, open_exporter, open_log_format,
                   resolve_schedule_triggers, _schedule_events)
from .spec import SpecError, extract, run_manifest


def _entities(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Entity"]


def compile_source(paths):
    return _compile(paths)[0]


def _module_name(paths):
    """RFC-0031: one file -> its basename (byte-identical to before this RFC);
    one directory -> the directory's basename; several explicit files -> the
    first one's basename (merge order is already deterministic, so its first
    element names the module)."""
    if len(paths) == 1 and os.path.isdir(paths[0]):
        return os.path.basename(os.path.normpath(paths[0]))
    return os.path.splitext(os.path.basename(paths[0]))[0]


def _source_display(paths):
    """One path as-is; several joined for a message (`--workflow` errors, the
    `serve` announce line) — nothing before this RFC ever saw a list here."""
    return paths[0] if len(paths) == 1 else ", ".join(paths)


def _compile(paths):
    """paths: [str], or (shorthand) a bare str for one path — file paths, or
    a single directory (RFC-0031). Every pre-RFC-0031 caller of this and
    `compile_source` passes a bare str; normalized once, here, so
    `_module_name` and `load_sources` both see a list.

    Returns (ir_document, decls, module_name, diagnostics).
    """
    if isinstance(paths, str):
        paths = [paths]
    decls = load_sources(paths)
    module_name = _module_name(paths)
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


STRICT_HELP = ("gate the exit code on diagnostics: bare `--strict` fails on any "
               "of them, `--strict=warning` only on warnings and above "
               "(so an intended `on schedule` or `performance` declaration "
               "stops blocking CI). `error` is reserved and matches no "
               "diagnostic today")


def _strict_level(value):
    """argparse `type` for `--strict`: a grade name, or a corrective rejection.

    Validated here rather than with `choices=` because of one shape. `--strict`
    takes its level with `nargs="?"`, so `lnpl compile --strict src.lnpl` hands
    the *path* over as the level; argparse's own message would list the choices
    and leave the author staring at a path that is obviously not one. Raising
    during conversion also puts the rejection before the command runs, so a
    usage error never emits half an IR document first.
    """
    if value in SEVERITIES:
        return value
    raise argparse.ArgumentTypeError(
        "takes one of %s, not %r — write `--strict=<level>`, or put `--strict` "
        "after the source if you meant the bare flag"
        % (", ".join(SEVERITIES), value))


def _strict_rc(args, rc, diagnostics):
    """Under `--strict`, a clean exit carrying gating diagnostics becomes rc 2.

    Only rc 0 is promoted. A non-zero rc already names a more specific failure
    (1 = the run/spec failed, 3 = runtime error, 4 = backend error) and
    overwriting it would trade a precise signal for a vaguer one. Reusing 2 puts
    the gate in the existing "rejected" class, so CI branches on one code
    (issue #45, t3 F-8). The diagnostic text on stderr is not touched.

    Which diagnostics gate is the caller's choice, not the code's (issue #52).
    `SEVERITIES` is ordered weakest-first, so the threshold is an index compare:
    bare `--strict` resolves to `info`, the lowest rung, which is exactly the
    "any diagnostic" behaviour that shipped in v0.3.0.
    """
    level = getattr(args, "strict", None)   # argparse already validated it
    if level is None or rc != 0:
        return rc
    floor = SEVERITIES.index(level)
    if any(SEVERITIES.index(d.severity) >= floor for d in diagnostics):
        return 2
    return rc


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
    return _strict_rc(args, 0, diagnostics)


class WorkflowSelectionError(Exception):
    """`--workflow` named an id this module does not declare."""


def _select_workflow(requested, source, workflows):
    """The workflow id to act on, or a rejection that lists the candidates.

    Issue #50 t3 F-7: the flag takes the derived node id (`wf.get.report`), not
    the declaration name (`GetReport`), and the derivation was undocumented. A
    wrong id used to reach the interpreter and come back as `no such workflow`
    with nothing to try next, so the only way forward was grepping the emitted
    IR. Validated here, at the boundary, the way a mistyped `--field` already is
    (issue #45): one message, every candidate, before any run or native build.

    An empty/omitted value means "unspecified" and selects the first workflow —
    the behaviour every caller without the flag already depends on.
    """
    if not requested:
        return workflows[0]["id"]
    ids = [n["id"] for n in workflows]
    if requested not in ids:
        raise WorkflowSelectionError(
            "error: --workflow %r is not a workflow of %s (valid: %s)"
            % (requested, source, ", ".join(ids)))
    return requested


class ScheduleSelectionError(Exception):
    """`--schedule` named an id this module declares no schedule event for."""


def _select_schedule_event(requested, source, events):
    """The schedule Event id `lnpl trigger --schedule` names, or a rejection
    that lists the candidates — mirrors `_select_workflow` (issue #81, D2):
    the derived node id (`event.daily.rollup`), validated at the boundary,
    one message naming every candidate. Unlike `--workflow`, there is no
    "first one" default (a cron entry has to name the schedule it means)
    and no empty-`requested` case to handle: `--schedule` is `required=True`
    in argparse, so `cmd_trigger` never reaches this with one.
    """
    ids = [n["id"] for n in events]
    if requested not in ids:
        raise ScheduleSelectionError(
            "error: --schedule %r is not a schedule event of %s (valid: %s)"
            % (requested, source, ", ".join(ids)))
    return requested


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
    target = _select_workflow(args.workflow, _source_display(args.source), workflows)

    rows = _repo_rows(doc, payload, target, empty=args.no_row)
    repository = _open_backend(getattr(args, "backend", "fake"))
    if repository is _REJECTED:
        return 2
    network_spec = getattr(args, "network", "fake")
    resolved = _open_endpoints(doc, getattr(args, "endpoint", None), network_spec)
    if resolved is _REJECTED:
        return 2
    endpoints, capabilities = resolved
    network = _open_network(network_spec, endpoints=endpoints,
                            capabilities=capabilities)
    if network is _REJECTED:
        return 2
    clock = _open_clock(getattr(args, "clock", "virtual"))
    if clock is _REJECTED:
        return 2
    try:
        interp = Interpreter(doc, repo_rows=rows, repository=repository,
                             network=network, clock=clock)
        result = interp.run_workflow(target, payload)
        # Compile-time and run-time findings are one report, not two.
        diagnostics.extend(interp.diagnostics)

        if args.json:
            # The diagnostics ride along as data, so CI can gate by grade
            # without parsing stderr (#52, r3 F-8). Always present, `[]` when
            # clean, so a consumer never branches on the key's existence.
            sys.stdout.write(_dump({"result": result,
                                    "trace": interp.trace.to_dict(),
                                    "diagnostics": to_records(diagnostics)}))
        else:
            _print_human(result, interp)
        _emit_diagnostics(diagnostics)
        return _strict_rc(args, 0 if result["status"] == "completed" else 1,
                          diagnostics)
    finally:
        # `finally`, so a failing run releases the store too. Leaving a
        # connection open is invisible in a one-shot CLI and a leak in the
        # server that reuses this path.
        if repository is not None:
            repository.close()
        if network is not None:
            network.close()


def _print_human(result, interp):
    root = interp.trace.root
    # Issue #44: the count rides on the FIRST line, because that is the only
    # line a caller skimming output is guaranteed to read — and without it a
    # rejected run and a fulfilled one printed byte-identical headers (t1 F-5,
    # t2 F-6). A run with no guard prints exactly what it printed before.
    skipped = result.get("skipped") or []
    note = ("  (%d step(s) skipped by guard)"
            % sum(len(r["steps"]) for r in skipped)) if skipped else ""
    print("workflow %s -> %s%s  (%sms, correlation_id=%s)"
          % (root.name if root else "?", result["status"], note,
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
    for record in skipped:
        # The guard's own text, so the reader learns WHY the step did not run
        # rather than only that something did not.
        print("  skipped by `%s %s`: %s"
              % (record["mode"], record["condition"] or "",
                 ", ".join(record["steps"]) or "(no step)"))
        for e in record.get("evaluations") or []:
            # Issue #83: the same evaluations[] the JSON trace carries (already
            # masked), printed for a reader who never asked for --json. No new
            # flag — always included (plan D4, simplicity over configurability).
            if e["expected"] is None:
                print("    %s %s (measured=%s)" % (e["ref"], e["op"], e["value"]))
            else:
                print("    %s %s %s (measured=%s)"
                      % (e["ref"], e["op"], e["expected"], e["value"]))
    for entry in interp.trace.logs:
        if entry["level"] in ("WARN", "ERROR"):
            print("  %-5s %s" % (entry["level"], entry["message"]))


def cmd_trigger(args):
    """`lnpl trigger <source...> --schedule <event-id>` (issue #81, D2): an
    external scheduler (cron/systemd) calls this directly — no `serve`
    socket, no built-in cron loop (the design this issue explicitly
    rejected). Same mode-A execution `cmd_run` already runs; the only
    difference from `run` is that the workflow is chosen by the declared
    schedule event's linkage (`resolve_schedule_triggers`, wsgi.py, D1)
    rather than by `--workflow`. Success is rc 0; a failed run (RunError, or
    `result["status"] != "completed"`) is rc != 0 — the same "0 or not" a
    cron entry already branches on for every other command.
    """
    doc, _, _, diagnostics = _compile(args.source)
    events = _schedule_events(doc)
    if not events:
        print("no `on schedule` event to trigger", file=sys.stderr)
        _emit_diagnostics(diagnostics)
        return 1
    target_event = _select_schedule_event(
        args.schedule, _source_display(args.source), events)
    event_node = next(n for n in events if n["id"] == target_event)
    triggers = resolve_schedule_triggers(doc, events=[event_node])
    target, _service = triggers[target_event]

    if args.payload:
        with open(args.payload, encoding="utf-8") as fh:
            payload = json.load(fh)
    else:
        payload = sample_payload(_entities(doc), refinement_index(doc))

    rows = _repo_rows(doc, payload, target)
    repository = _open_backend(getattr(args, "backend", "fake"))
    if repository is _REJECTED:
        return 2
    network_spec = getattr(args, "network", "fake")
    resolved = _open_endpoints(doc, getattr(args, "endpoint", None), network_spec)
    if resolved is _REJECTED:
        return 2
    endpoints, capabilities = resolved
    network = _open_network(network_spec, endpoints=endpoints,
                            capabilities=capabilities)
    if network is _REJECTED:
        return 2
    clock = _open_clock(getattr(args, "clock", "virtual"))
    if clock is _REJECTED:
        return 2
    try:
        interp = Interpreter(doc, repo_rows=rows, repository=repository,
                             network=network, clock=clock)
        result = interp.run_workflow(target, payload)
        diagnostics.extend(interp.diagnostics)
        _print_human(result, interp)
        _emit_diagnostics(diagnostics)
        return _strict_rc(args, 0 if result["status"] == "completed" else 1,
                          diagnostics)
    finally:
        if repository is not None:
            repository.close()
        if network is not None:
            network.close()


# `every` -> a function of (hour, minute) -> the crontab 5-field expression.
# A closed table (issue #81, D3), the same size as `lexer.SCHEDULE_RECURRENCES`
# it mirrors: RFC-0016 accepts only `daily` today, and each new recurrence
# RFC-0016 admits gets exactly one new row here, never a guessed mapping.
_CRONTAB_EXPR = {
    "daily": lambda hh, mm: "%d %d * * *" % (mm, hh),
}

_GENERATED_HEADER = (
    "# generated by `lnpl schedules` from %s — do not hand-edit; re-run the "
    "command instead (issue #81, D3)"
)


def _crontab_snippet(entry, event_name, trigger_cmd):
    hh, mm = (int(p) for p in entry["at"].split(":"))
    expr = _CRONTAB_EXPR[entry["every"]](hh, mm)
    # SCHEDULE_ZONES is fixed to ("UTC",) — RFC-0016 accepts no other zone —
    # so the assumption below is always true today, stated rather than
    # silently relied on.
    return ("# %s: %s at %s %s (assumes the cron daemon's clock is %s)\n"
            "%s %s"
            % (event_name, entry["every"], entry["at"], entry["zone"],
               entry["zone"], expr, trigger_cmd))


def _systemd_snippet(entry, event_name, slug, trigger_cmd):
    hh, mm = entry["at"].split(":")
    return (
        "# %s.timer\n"
        "[Unit]\n"
        "Description=lnpl schedule trigger: %s (RFC-0016)\n\n"
        "[Timer]\n"
        "OnCalendar=*-*-* %s:%s:00 %s\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n\n"
        "# %s.service\n"
        "[Unit]\n"
        "Description=lnpl trigger: %s\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "ExecStart=%s\n"
        % (slug, event_name, hh, mm, entry["zone"], slug, event_name, trigger_cmd))


def cmd_schedules(args):
    """`lnpl schedules <source...> --format crontab|systemd` (issue #81,
    D3): every declared `on schedule` trigger, rendered as the external
    scheduler snippet that calls `lnpl trigger` — consumes
    `x-lnpl-schedules` (`openapi.generate`'s existing metadata, not
    regenerated here) rather than re-deriving the schedule fields.
    """
    doc, _, _, diagnostics = _compile(args.source)
    schedules = generate_openapi(doc).get("x-lnpl-schedules", [])
    if not schedules:
        print("no `on schedule` event declared in %s" % _source_display(args.source),
             file=sys.stderr)
        _emit_diagnostics(diagnostics)
        return 1
    nodes = {n["id"]: n for n in doc["nodes"]}
    source_args = " ".join(args.source)
    blocks = [_GENERATED_HEADER % _source_display(args.source)]
    for entry in schedules:
        event = nodes[entry["event"]]
        trigger_cmd = "lnpl trigger %s --schedule %s" % (source_args, entry["event"])
        if args.format == "crontab":
            blocks.append(_crontab_snippet(entry, event["name"], trigger_cmd))
        else:
            blocks.append(_systemd_snippet(entry, event["name"], _slug(event["name"]),
                                           trigger_cmd))
    text = "\n\n".join(blocks) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s (%d schedule(s))" % (args.output, len(schedules)))
    else:
        sys.stdout.write(text)
    _emit_diagnostics(diagnostics)
    return 0


def cmd_spec(args):
    # The diagnostics matter most here: `spec` is the command whose job is
    # verification, so a step that derives no Effect (#36) is exactly what its
    # operator needs told. `compile` and `run` already report them; this dropped
    # the accumulator on the floor.
    doc, decls, module_name, diagnostics = _compile(args.source)
    _emit_diagnostics(diagnostics)
    manifest = extract(decls, module_name)
    if not manifest["cases"]:
        print("no `spec` block found in %s" % _source_display(args.source),
             file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(_dump(manifest))
        print("wrote %s (%d case(s))" % (args.output, len(manifest["cases"])))
        if not args.run:
            return _strict_rc(args, 0, diagnostics)
    elif not args.run:
        sys.stdout.write(_dump(manifest))
        return _strict_rc(args, 0, diagnostics)

    passed, failed, lines = run_manifest(manifest, doc)
    for line in lines:
        print(line)
    print("spec: %d passed, %d failed" % (passed, failed))
    return _strict_rc(args, 0 if failed == 0 else 1, diagnostics)


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


def cmd_serve(args):
    """Issue #26: bind the workflows to their OpenAPI paths over HTTP (mode A).

    The status-code mapping is normative in docs/serving.md. SIGINT is the
    shutdown path: `serve_forever` surfaces it as KeyboardInterrupt, the socket
    closes, and the exit code stays 0 — stopping a server on request is not a
    failure.
    """
    doc, _, _, diagnostics = _compile(args.source)
    _emit_diagnostics(diagnostics)
    if not any(n["kind"] == "Workflow" for n in doc["nodes"]):
        print("no workflow to serve", file=sys.stderr)
        return 1

    # Both are validated before the socket is bound. A store that cannot be
    # opened, or a signing secret that is not set, is a failed launch — finding
    # either out on the first request instead means the server came up and is
    # quietly not the one that was asked for.
    backend = getattr(args, "backend", "fake")
    probe = _open_backend(backend)
    if probe is _REJECTED:
        return 2
    if probe is not None:
        probe.close()
    token_provider = _token_provider(getattr(args, "jwt_secret_env", None))
    if token_provider is _REJECTED:
        return 2
    network_spec = getattr(args, "network", "fake")
    resolved = _open_endpoints(doc, getattr(args, "endpoint", None), network_spec)
    if resolved is _REJECTED:
        return 2
    endpoints, capabilities = resolved
    network = _open_network(network_spec, endpoints=endpoints,
                            capabilities=capabilities)
    if network is _REJECTED:
        return 2
    log_format = _open_log_format(getattr(args, "log_format", "text"))
    if log_format is _REJECTED:
        return 2
    exporter = _open_trace_exporter(getattr(args, "trace_exporter", None))
    if exporter is _REJECTED:
        return 2

    factory = None if backend == "fake" else (lambda: open_repository(backend))
    server = serve(doc, args.host, args.port, repository_factory=factory,
                   token_provider=token_provider, network=network,
                   log_format=log_format, exporter=exporter,
                   trust_incoming_trace=getattr(args, "trust_incoming_trace", False))
    host, port = server.server_address[:2]
    # flush: with stdout piped (the normal way to capture the port), a buffered
    # announce line never reaches the reader while serve_forever blocks.
    print("serving %s on http://%s:%d (mode A, backend=%s, jwt=%s)"
          % (_source_display(args.source), host, port,
             "fake" if backend == "fake" else backend.split(":", 1)[0],
             "verified" if token_provider is not None else "presence-checked"),
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_outbox_drain(args):
    """`lnpl outbox drain --backend sqlite:...` — every undelivered emission,
    JSON Lines on stdout, oldest first (issue #102, D3). `ack` is the only
    thing that removes a row from this view; draining twice without acking
    shows the same rows both times, which is the at-least-once contract.
    """
    repository = _open_backend(args.backend)
    if repository is _REJECTED:
        return 2
    if repository is None:
        print("error: outbox drain needs a persistent --backend "
              "(e.g. sqlite:./store.db) — `fake` has no outbox to drain",
              file=sys.stderr)
        return 2
    try:
        for emission in repository.drain_outbox(limit=args.limit):
            sys.stdout.write(json.dumps(emission, ensure_ascii=False) + "\n")
        return 0
    except DriverError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    finally:
        repository.close()


def cmd_outbox_ack(args):
    """`lnpl outbox ack --backend sqlite:... <seq>...` — mark each row
    delivered. `seq` (not `emission_id`) is the row's identity: a run of the
    same document against the same store can legitimately reproduce an
    `emission_id` a prior run already used (interp.py's counter is local to
    one Interpreter instance), so `seq` — sqlite's own AUTOINCREMENT, and
    `drain`'s first field on every line — is what `ack` addresses. Idempotent
    on a re-ack; an unknown seq fails closed (naming it, rc != 0) before
    anything is written (issue #102, D3 revised).
    """
    repository = _open_backend(args.backend)
    if repository is _REJECTED:
        return 2
    if repository is None:
        print("error: outbox ack needs a persistent --backend "
              "(e.g. sqlite:./store.db) — `fake` has no outbox to ack",
              file=sys.stderr)
        return 2
    try:
        repository.ack_outbox(args.seq)
        return 0
    except DriverError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    finally:
        repository.close()


def cmd_db_check(args):
    """`lnpl db check <source...> --backend sqlite:...` — every stored row of
    every declared entity, checked against its declaration (issue #85).
    JSON on stdout — `[]` and rc 0 when every row matches, the mismatched
    rows (never a value, D2) and rc 1 when at least one does not — for an
    external backfill tool to consume and re-run this against, rather than
    this reading the DB one `run` at a time.
    """
    doc = compile_source(args.source)
    repository = _open_backend(args.backend)
    if repository is _REJECTED:
        return 2
    if repository is None:
        print("error: db check needs a persistent --backend "
              "(e.g. sqlite:./store.db) — `fake` has no rows to check",
              file=sys.stderr)
        return 2
    refinements = refinement_index(doc)
    findings = []
    try:
        for entity_node in _entities(doc):
            try:
                rows = repository.query(entity_node["id"])
            except DriverError as exc:
                print("error: %s" % exc, file=sys.stderr)
                return 1
            for row in rows:
                for mismatch in row_shape_mismatches(entity_node, row, refinements):
                    findings.append({"entity": entity_node["name"],
                                     "row_key": row_key(entity_node["id"], row),
                                     "field": mismatch["field"],
                                     "expected_type": mismatch["expected_type"],
                                     "kind": mismatch["kind"]})
    finally:
        repository.close()
    sys.stdout.write(json.dumps(findings, indent=2, ensure_ascii=False) + "\n")
    return 1 if findings else 0


# Distinguishes "the operator asked for the default in-memory store" (None,
# which the Interpreter turns into its FakeRepository) from "the selector was
# rejected" — two answers `open_repository` cannot both return as None.
_REJECTED = object()


def _open_backend(spec):
    """`--backend`'s value -> a driver, None for the fake, `_REJECTED` on a bad
    selector (the caller then exits 2, having already printed why).

    Opened here, before the run, so a store that cannot be reached is an
    operator error at the boundary — the same rc a mistyped `--field` gets —
    rather than a failed workflow that reads as the program's fault.
    """
    try:
        return open_repository(spec)
    except (ValueError, DriverError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return _REJECTED


def _open_network(spec, endpoints=None, capabilities=None):
    """`--network`'s value -> a NetworkDriver, None for the fake, `_REJECTED`
    on a bad selector — the `_open_backend` selector mirrored (RFC-0027 §1).

    `endpoints`/`capabilities` (issue #101) are already resolved by
    `_open_endpoints` and just threaded through to `open_network`.
    """
    try:
        return open_network(spec, endpoints=endpoints, capabilities=capabilities)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return _REJECTED


def _network_targets(doc):
    """Every `NetworkCall.target` in `doc` that is a logical name, not a URL
    literal, deduplicated in first-appearance order (issue #101 D3) — the
    set `_open_endpoints` must resolve under `--network http`."""
    seen = []
    for n in doc["nodes"]:
        if n["kind"] != "NetworkCall":
            continue
        target = n["target"]
        if target not in seen and not _is_url_literal(target):
            seen.append(target)
    return seen


def _http_capabilities(doc):
    """name -> {"method", "auth"} for every declared `capability http` node
    (issue #101) — `method` is present only on those, so it doubles as the
    filter for "is this Capability node an http one"."""
    return {n["name"]: {"method": n["method"], "auth": n.get("auth")}
            for n in doc["nodes"] if n["kind"] == "Capability" and "method" in n}


def _open_endpoints(doc, endpoint_args, network_spec):
    """`--endpoint`/`LNPL_ENDPOINT_*` + declared `capability http` auth ->
    (endpoints, capabilities) for `HttpNetworkDriver`, or `_REJECTED`.

    Issue #101 D3/D5: validated before the run/serve starts — a `--network
    http` module whose compiled `NetworkCall` targets do not all resolve, or
    whose declared auth names an unset environment variable, is a failed
    launch, the same rc 2 `_open_backend`/`_token_provider` already give a
    bad selector or a missing secret. `--network fake` skips all of it: the
    fake driver has no notion of either (D7).
    """
    caps = _http_capabilities(doc)
    if network_spec != "http":
        return {}, caps
    given = {}
    for item in endpoint_args or []:
        name, sep, url = item.partition("=")
        if not sep:
            print("error: --endpoint %r is not NAME=URL" % item, file=sys.stderr)
            return _REJECTED
        given[name] = url
    endpoints = {}
    resolved_caps = {}
    for name in _network_targets(doc):
        # CLI wins over env (D2: explicit beats implicit).
        url = given.get(name)
        if url is None:
            url = os.environ.get("LNPL_ENDPOINT_%s" % name.upper())
        if url is None:
            print("error: network target %r has no --endpoint mapping or "
                  "LNPL_ENDPOINT_%s environment variable — map it with "
                  "`--endpoint %s=<url>` or set LNPL_ENDPOINT_%s"
                  % (name, name.upper(), name, name.upper()), file=sys.stderr)
            return _REJECTED
        endpoints[name] = url
        cap = caps.get(name)
        if cap is None:
            # declared-not-bound (D4): a legitimate, undeclared logical name
            # still calls out — method POST, no auth, the pre-#101 default.
            resolved_caps[name] = {"method": "POST", "headers": {}}
            continue
        headers = {}
        auth = cap.get("auth")
        if auth is not None:
            value = os.environ.get(auth["env"])
            if value is None:
                print("error: %s is not set in the environment (capability "
                      "http %s declares `auth %s from %s`)"
                      % (auth["env"], name, auth["kind"], auth["env"]),
                      file=sys.stderr)
                return _REJECTED
            if auth["kind"] == "bearer":
                headers["Authorization"] = "Bearer %s" % value
            else:
                headers[auth["header"]] = value
        resolved_caps[name] = {"method": cap["method"].upper(), "headers": headers}
    return endpoints, resolved_caps


def _open_clock(spec):
    """`--clock`'s value -> a Clock instance, None for the default virtual
    binding, `_REJECTED` on a bad selector — the `_open_backend`/
    `_open_network` selectors mirrored (RFC-0029 §Execution Model/Clock).
    """
    try:
        return open_clock(spec)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return _REJECTED


def _open_log_format(spec):
    """`--log-format`'s value -> itself validated, `_REJECTED` on a bad
    selector (issue #78 — the `_open_clock` selector shape mirrored)."""
    try:
        return open_log_format(spec)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return _REJECTED


def _open_trace_exporter(spec):
    """`--trace-exporter`'s value -> a TraceExporter, None for unset,
    `_REJECTED` on a bad selector or a load failure (issue #78)."""
    try:
        return open_exporter(spec)
    except (ValueError, ExporterError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return _REJECTED


def _token_provider(secret_env):
    """`--jwt-secret-env`'s value -> a provider, None when unset, `_REJECTED`
    when the named variable is missing or too short.

    The variable's NAME is what the operator passes and what any message
    quotes; the value is read here and never printed, logged, or put in an
    exception. Validated before the workflow starts for the same reason the
    store is: a secret discovered missing mid-request is an incident, and one
    discovered at startup is a failed launch.
    """
    if secret_env is None:
        return None
    secret = os.environ.get(secret_env)
    if not secret:
        print("error: %s is not set in the environment" % secret_env,
              file=sys.stderr)
        return _REJECTED
    try:
        return HmacTokenProvider(secret)
    except TokenError as exc:
        print("error: %s (from %s)" % (exc, secret_env), file=sys.stderr)
        return _REJECTED


def cmd_token(args):
    """Issue a bearer token for one served path (issue #25).

    The audience is derived from the path rather than configured, so the token
    this prints and the check `lnpl serve` runs read the same function and
    cannot drift. A path the server does not serve is rejected here with the
    served set listed — a token for a path that does not exist would fail at
    request time with nothing to point at.
    """
    doc, _, _, _ = _compile(args.source)
    routes = build_routes(doc)
    if args.path not in routes:
        print("error: --path %r is not served (valid: %s)"
              % (args.path, ", ".join(sorted(routes))), file=sys.stderr)
        return 2
    provider = _token_provider(args.secret_env)
    if provider is _REJECTED:
        return 2
    try:
        ttl_ms = _duration_ms(args.ttl)
        print(provider.issue(args.subject, audience_for_path(args.path), ttl_ms))
    except (TokenError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


def _repo_rows(doc, payload, workflow_id, empty=False):
    if empty:
        return {}
    return default_rows(doc, workflow_id, payload)


def _unknown_condition_fields(doc, workflow_id, fields):
    """The `--field` names this workflow has no comparison guard for.

    `condition_field_names` is the single source of truth the emitter, the C
    runtime and `run_binary` all read, so the allowlist is that list rather than
    a second derivation that could drift from it.
    """
    valid = set(condition_field_names(doc, workflow_id))
    return sorted(set(fields) - valid)


def cmd_build(args):
    doc = compile_source(args.source)
    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to build", file=sys.stderr)
        return 1
    target = _select_workflow(args.workflow, _source_display(args.source), workflows)
    # Issue #55 (r1 N-3): say where this build's Validation outcome came from,
    # BEFORE the `--field` check below can end the command with rc 2. That is the
    # exact path the misreading took — `--field slug=1` on a refinement-bearing
    # workflow was rejected with `valid: (none)`, which is true and explains
    # nothing. Emitted for the build, not the run: mode B decides the outcome at
    # compile time, so `--run` is irrelevant to whether it holds.
    diagnostics = Diagnostics()
    validated = validation_effect_steps(doc, target)
    if validated:
        diagnostics.add(
            code="validation-sample-derived",
            where=target,
            subject=", ".join(validated),
            message="mode B decides the Validation outcome at build time from a "
                    "derived sample payload, which is valid by construction — so "
                    "no --field value can make a refinement fail here. --field "
                    "drives comparison guards only; use `lnpl run --payload` "
                    "(mode A) to exercise refinement enforcement")
    _emit_diagnostics(diagnostics)
    # Validate --field here, at the boundary, and before the native build: a
    # name no guard compares on cannot change the run whatever its value, so it
    # is always a typo. Silently dropping it left the guard reading the default
    # 0 and the run reporting success (issue #45, t4 F-3).
    try:
        fields = _parse_fields(args.field)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if fields:
        unknown = _unknown_condition_fields(doc, target, fields)
        if unknown:
            valid = condition_field_names(doc, target)
            print("error: --field name(s) %s do not match any comparison-guard "
                  "field of workflow %s (valid: %s)"
                  % (", ".join(unknown), target,
                     ", ".join(valid) if valid else "(none)"),
                  file=sys.stderr)
            return 2
    path = build_native(doc, target, args.workdir)
    print("native binary: %s" % path)
    if args.run:
        rc, lines = run_binary(path, skip=args.skip, condition_fields=fields)
        print("\n".join(lines))
        # Issue #55 (r1 N-2, r1 F-5): the binary prints nothing for a step its
        # guard refused, so mode B's rejection was invisible here while mode A
        # reported the same fact three ways. `restore_skips` reads the absence
        # against the compiled plan — the reading RFC-0014 §2.6 already made
        # normative for mode B — so nothing about the emitted module changes.
        #
        # `build_native` above was called without `seeded`/`payload`, so the plan
        # must be derived with those same defaults or it would describe a
        # different specialisation than the one that ran.
        skips = restore_skips(doc, target, ran_step_indices(lines))
        if skips:
            print("  (%d step(s) skipped by guard, restored from the compiled "
                  "plan)" % len(skips))
            diagnostics = Diagnostics()
            for record in skips:
                # The guard's own text, so the reader learns WHY the step did not
                # run rather than only that something did not.
                print("  skipped by `%s %s`: %s"
                      % (record["mode"], record["condition"] or "",
                         record["step"]))
                # `where` is the workflow id, not the guard's: mode B's observation
                # surface has no IR node ids at all (RFC-0014 §2.4), so the
                # workflow is the finest site it can honestly name. One record per
                # STEP, because grouping by guard is a mode A channel — see
                # rfcs/0022 for both differences.
                diagnostics.add(
                    code="guard-skipped-steps",
                    where=target,
                    subject=record["condition"] or "(unconditional)",
                    message="the `%s` guard did not run %s; mode B's binary "
                            "prints nothing for a step it skips, so this record "
                            "is restored from the compiled step plan "
                            "(RFC-0014 §2.6)"
                            % (record["mode"], record["step"]))
            _emit_diagnostics(diagnostics)
        print("exit=%d" % rc)
    return 0


def cmd_diff(args):
    doc = compile_source(args.source)
    workflows = [n for n in doc["nodes"] if n["kind"] == "Workflow"]
    if not workflows:
        print("no workflow to compare", file=sys.stderr)
        return 1
    target = _select_workflow(args.workflow, _source_display(args.source), workflows)
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
    ap.add_argument("--version", action="version",
                    version="lnpl %s" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compile", help="parse and lower to Semantic IR")
    c.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    c.add_argument("-o", "--output")
    c.add_argument("--strict", nargs="?", const="info", default=None,
                     type=_strict_level, metavar="LEVEL", help=STRICT_HELP)
    c.set_defaults(func=cmd_compile)

    r = sub.add_parser("run", help="compile then execute (interpreter mode A)")
    r.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    r.add_argument("--payload", help="JSON file with the workflow input")
    r.add_argument("--workflow", help="workflow node id (default: the first one)")
    r.add_argument("--json", action="store_true", help="emit result and trace as JSON")
    r.add_argument("--no-row", action="store_true",
                   help="start with an empty repository (exercises retry)")
    r.add_argument("--backend", default="fake", help="capability backend: `fake` (default, in-memory, per-run) or `sqlite:<path>` for a store that persists")
    r.add_argument("--network", default="fake", help="NetworkCall driver: `fake` (default, deterministic, no I/O) or `http` (real requests via http.client)")
    r.add_argument("--endpoint", action="append", metavar="NAME=URL", default=[],
                   help="map a logical NetworkCall target to a URL under --network http (repeatable; also settable via LNPL_ENDPOINT_<NAME>, --endpoint wins)")
    r.add_argument("--clock", default="virtual", help="time binding: `virtual` (default, deterministic, process-local) or `real` (monotonic wall clock — binds CacheAccess TTL to actual elapsed time)")
    r.add_argument("--strict", nargs="?", const="info", default=None,
                     type=_strict_level, metavar="LEVEL", help=STRICT_HELP)
    r.set_defaults(func=cmd_run)

    tg = sub.add_parser("trigger",
                        help="run a declared `on schedule` event's linked "
                             "workflow (interpreter mode A) — the entry "
                             "point an external scheduler calls; no "
                             "built-in cron (issue #81)")
    tg.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    tg.add_argument("--schedule", required=True, metavar="EVENT-ID",
                    help="the schedule event's node id (e.g. "
                         "event.daily.rollup) — see `lnpl schedules` for "
                         "the id each declared `on schedule` event derives")
    tg.add_argument("--payload", help="JSON file with the workflow input")
    tg.add_argument("--backend", default="fake", help="capability backend: `fake` (default, in-memory, per-run) or `sqlite:<path>` for a store that persists")
    tg.add_argument("--network", default="fake", help="NetworkCall driver: `fake` (default, deterministic, no I/O) or `http` (real requests via http.client)")
    tg.add_argument("--endpoint", action="append", metavar="NAME=URL", default=[],
                    help="map a logical NetworkCall target to a URL under --network http (repeatable; also settable via LNPL_ENDPOINT_<NAME>, --endpoint wins)")
    tg.add_argument("--clock", default="virtual", help="time binding: `virtual` (default, deterministic, process-local) or `real` (monotonic wall clock — binds CacheAccess TTL to actual elapsed time)")
    tg.add_argument("--strict", nargs="?", const="info", default=None,
                     type=_strict_level, metavar="LEVEL", help=STRICT_HELP)
    tg.set_defaults(func=cmd_trigger)

    sc = sub.add_parser("schedules",
                        help="render every declared `on schedule` event as "
                             "an external-scheduler snippet that calls "
                             "`lnpl trigger` (issue #81)")
    sc.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    sc.add_argument("--format", choices=("crontab", "systemd"), default="crontab",
                    help="snippet shape: `crontab` (default, a 5-field line "
                         "per schedule) or `systemd` (a .timer + .service "
                         "unit pair per schedule)")
    sc.add_argument("-o", "--output", help="write the snippet to this path")
    sc.set_defaults(func=cmd_schedules)

    sp = sub.add_parser("spec", help="extract `spec` blocks as a test manifest")
    sp.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    sp.add_argument("-o", "--output", help="write the manifest to this path")
    sp.add_argument("--run", action="store_true", help="execute the manifest")
    sp.add_argument("--strict", nargs="?", const="info", default=None,
                     type=_strict_level, metavar="LEVEL", help=STRICT_HELP)
    sp.set_defaults(func=cmd_spec)

    oa = sub.add_parser("openapi", help="generate an OpenAPI 3.1 document from the IR")
    oa.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    oa.add_argument("-o", "--output")
    oa.set_defaults(func=cmd_openapi)

    sv = sub.add_parser("serve",
                        help="serve workflows over HTTP at the OpenAPI paths "
                             "(interpreter mode A, fake backend)")
    sv.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    sv.add_argument("--host", default="127.0.0.1",
                    help="bind address (default: 127.0.0.1 — loopback only)")
    sv.add_argument("--port", type=int, default=8080,
                    help="TCP port; 0 binds an ephemeral port (default: 8080)")
    sv.add_argument("--backend", default="fake", help="capability backend: `fake` (default, in-memory, per-run) or `sqlite:<path>` for a store that persists")
    sv.add_argument("--network", default="fake", help="NetworkCall driver: `fake` (default, deterministic, no I/O) or `http` (real requests via http.client)")
    sv.add_argument("--endpoint", action="append", metavar="NAME=URL", default=[],
                    help="map a logical NetworkCall target to a URL under --network http (repeatable; also settable via LNPL_ENDPOINT_<NAME>, --endpoint wins)")
    sv.add_argument("--jwt-secret-env", default=None, metavar="NAME",
                    help="name of the environment variable holding the HS256 "
                         "signing secret. Given, `security jwt` services verify "
                         "the bearer token; omitted, the header is only checked "
                         "for presence. The value is never read from the "
                         "command line.")
    sv.add_argument("--log-format", default="text",
                    help="access-log line shape: `text` (default, silent — no "
                         "access log) or `json` (one JSON Line per request to "
                         "stderr: correlation_id/method/path/workflow/status/"
                         "duration_ms/skipped/diagnostics)")
    sv.add_argument("--trace-exporter", default=None, metavar="NAME",
                    help="export each completed request's Trace: built-in "
                         "`stderr-json`, or a name registered under the "
                         "`lnpl.exporters` entry-points group; omitted, "
                         "nothing is exported (independent of --log-format)")
    sv.add_argument("--trust-incoming-trace", action="store_true",
                    help="adopt an inbound `traceparent` header's trace-id "
                         "for this request (default: off). Off means a "
                         "malformed OR untrusted inbound traceparent never "
                         "changes the request's own trace-id: a new one is "
                         "always minted, and the inbound value is recorded "
                         "only as a link, never adopted outright")
    sv.set_defaults(func=cmd_serve)

    tk = sub.add_parser("token",
                        help="issue a bearer token for one served path (#25)")
    tk.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    tk.add_argument("--path", required=True, metavar="PATH",
                    help="the served path the token is for, e.g. /shop/checkout")
    tk.add_argument("--subject", required=True,
                    help="the `sub` claim — who the token speaks for")
    tk.add_argument("--secret-env", required=True, metavar="NAME",
                    help="name of the environment variable holding the HS256 "
                         "signing secret (never the secret itself)")
    tk.add_argument("--ttl", default="15m",
                    help="access-token lifetime (default: 15m)")
    tk.set_defaults(func=cmd_token)

    ob = sub.add_parser("outbox",
                        help="drain/ack the lnpl_outbox — at-least-once emit "
                             "delivery (issue #102)")
    ob_sub = ob.add_subparsers(dest="outbox_cmd", required=True)

    obd = ob_sub.add_parser("drain",
                            help="print undelivered emissions as JSON Lines, "
                                 "oldest first")
    obd.add_argument("--backend", required=True, metavar="sqlite:PATH",
                     help="a persistent capability backend, e.g. sqlite:./store.db "
                          "(`fake` has no outbox to drain)")
    obd.add_argument("--limit", type=int, default=None,
                     help="cap the number of emissions printed (default: unlimited)")
    obd.set_defaults(func=cmd_outbox_drain)

    oba = ob_sub.add_parser("ack", help="mark one or more outbox rows delivered")
    oba.add_argument("--backend", required=True, metavar="sqlite:PATH",
                     help="a persistent capability backend, e.g. sqlite:./store.db "
                          "(`fake` has no outbox to ack)")
    oba.add_argument("seq", nargs="+", type=int,
                     help="one or more `seq` values (from `outbox drain`'s "
                          "output) to mark delivered — a repeated or "
                          "already-delivered seq is a no-op success")
    oba.set_defaults(func=cmd_outbox_ack)

    db = sub.add_parser("db",
                        help="inspect a persistent store against the "
                             "declared schema (issue #85)")
    db_sub = db.add_subparsers(dest="db_cmd", required=True)

    dbc = db_sub.add_parser("check",
                            help="scan every stored row against the "
                                 "declared entities; print mismatches as "
                                 "JSON, rc 1 iff any (rc 0 clean)")
    dbc.add_argument("source", nargs="+",
                     help="one or more .lnpl files (merged in the given "
                          "order), or a single directory (its *.lnpl, "
                          "filename-sorted — RFC-0031, issue #77)")
    dbc.add_argument("--backend", required=True, metavar="sqlite:PATH",
                     help="a persistent capability backend, e.g. "
                          "sqlite:./store.db (`fake` has no rows to check)")
    dbc.set_defaults(func=cmd_db_check)

    bd = sub.add_parser("build", help="compile to a native binary (mode B)")
    bd.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    bd.add_argument("--workflow")
    bd.add_argument("--workdir", default=".claude/tmp/lnpl-build")
    bd.add_argument("--run", action="store_true")
    bd.add_argument("--field", action="append", metavar="NAME=VALUE", default=[],
                    help="condition field value for a `when`/`until` comparison "
                         "guard, e.g. --field counter=12 (repeatable). NAME must "
                         "name a comparison-guard field of the workflow — one that "
                         "does not is rejected, with the valid names listed. "
                         "Omitted fields default to 0. Comparison guards only: "
                         "refinement/validation values are not injectable through "
                         "this flag, because mode B derives the Validation outcome "
                         "at build time from a sample payload — use `lnpl run "
                         "--payload` (mode A) for refinement enforcement.")
    bd.add_argument("--skip", action="store_true",
                    help="set the Presence `when` guard flag so steps guarded by "
                         "an exists/missing check are skipped. Comparison guards "
                         "are driven by --field, not by this flag.")
    bd.set_defaults(func=cmd_build)

    df = sub.add_parser("diff", help="differential check: mode A vs mode B")
    df.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
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
    ag.add_argument("source", nargs="+",
                    help="one or more .lnpl files (merged in the given order), "
                         "or a single directory (its *.lnpl, filename-sorted — "
                         "RFC-0031, issue #77)")
    ag.add_argument("--root", default=None, help="KB root")
    ag.add_argument("-o", "--output", help="write the resulting IR here")
    ag.set_defaults(func=cmd_agents)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (WorkflowSelectionError, ScheduleSelectionError) as exc:
        # Operator error, like a mistyped --field: rc 2, message already carries
        # the candidates, and no "compile error:" prefix — nothing failed to
        # compile (issue #50; issue #81 D2 for --schedule).
        print(str(exc), file=sys.stderr)
        return 2
    except (LexError, ParseError, LowerError, SpecError, OpenApiError,
            ServeError, KbError) as exc:
        print("compile error: %s" % exc, file=sys.stderr)
        return 2
    except RunError as exc:
        print("runtime error: %s" % exc, file=sys.stderr)
        return 3
    except (BackendError, DifferentialError) as exc:
        print("backend error: %s" % exc, file=sys.stderr)
        return 4
