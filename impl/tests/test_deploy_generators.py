"""Built-in compose and k8s generators (issues #189, #236): unit tests. All are
hermetic (no docker, no network) except KubeconformTest, which runs the pinned
kubeconform container through docker and fetches schemas from
raw.githubusercontent.com. The docker-backed checks live in
examples/deploy/test_deploy.py and are run by hand.

Goldens under impl/tests/golden/deploy/ are regenerated only with the CLI from the worktree root, no --set:
PYTHONPATH=impl .venv/bin/python -m lnpl generate compose impl/tests/golden/deploy/<fixture>.lnpl --out impl/tests/golden/deploy/<fixture>
PYTHONPATH=impl .venv/bin/python -m lnpl generate k8s impl/tests/golden/deploy/<fixture>.lnpl --out impl/tests/golden/deploy/<fixture>
then read git diff impl/tests/golden/deploy before committing. There is no auto-update switch.
"""

import codecs
import contextlib
import inspect
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from lnpl import cli
from lnpl.deploy_gen import (COMPOSE_OPTIONS, GRACE_PERIOD_S, K8S_OPTIONS,
                             auth_env_vars, check_object_name, check_options,
                             check_quantity,
                             classify_capabilities, compose_quote,
                             endpoint_keys, generate_compose, generate_k8s,
                             parse_port, parse_replicas, warn_unknown,
                             yaml_quote)
from lnpl.generators import GeneratorError, run_generator
from lnpl.testing import GeneratorTCK
from lnpl.wsgi import ServeError

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN = os.path.join(REPO, "impl", "tests", "golden", "deploy")
SCRATCH = os.path.join(REPO, ".claude", "tmp", "test_deploy_generators")
FIXTURES = ("pg-redis", "no-caps", "unknown-cap", "jwt-http")
HOSTILE_VALUE = "a: b # c 'q' \"dq\"\n- *x $HOME"
KUBECONFORM_IMAGE = ("ghcr.io/yannh/kubeconform:v0.6.7@sha256:"
                     "0925177fb05b44ce18574076141b5c3d83235e1904d3f952182ac99ddc45762c")
KUBECONFORM_CMD = ["docker", "run", "--rm", "-i", KUBECONFORM_IMAGE, "-strict",
                   "-summary", "-kubernetes-version", "1.30.0", "-"]
ALL_OPTIONS = {"ingress_host": "api.example.com", "hpa_min": "2", "hpa_max": "5",
               "hpa_cpu": "70", "cpu_request": "100m", "pdb": "true",
               "network_policy": "true",
               "egress_cidrs": "203.0.113.0/24,2001:db8::/32"}
_NO_DOCKER = ("docker not reachable; kubeconform runs as " + KUBECONFORM_IMAGE
              + " — set LNPL_REQUIRE_KUBECONFORM=1 to make this a failure")


def _doc(fixture):
    return cli.compile_source([os.path.join(GOLDEN, fixture + ".lnpl")])


def _doc_with_auth(env):
    """jwt-http with `auth bearer from <env>` on PaymentGateway, built by hand
    (the IR shape `drivers._http_capabilities` reads)."""
    doc = _doc("jwt-http")
    nodes = []
    for node in doc["nodes"]:
        if node["kind"] == "Capability" and node.get("name") == "PaymentGateway":
            node = dict(node, auth={"kind": "bearer", "env": env})
        nodes.append(node)
    return dict(doc, nodes=nodes)


def _golden(fixture, name):
    with open(os.path.join(GOLDEN, fixture, name), "rb") as fh:
        return fh.read()


def _quiet(generator, document, options):
    """Run a generator with its stderr warning captured; -> (bytes, stderr)."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        out = generator(document, options)
    return out, err.getvalue()


def _text(generator, key, fixture, options=None):
    out, _ = _quiet(generator, _doc(fixture), options or {})
    return out[key].decode("ascii")


def _kinds(text):
    return re.findall(r"^kind: (\w+)$", text, re.M)


def _documents(text):
    return text.split("\n---\n")


def _kubeconform_ready():
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        return False
    return probe.returncode == 0


def _require_kubeconform(test):
    if _kubeconform_ready():
        return
    if os.environ.get("LNPL_REQUIRE_KUBECONFORM") == "1":
        test.fail(_NO_DOCKER)
    test.skipTest(_NO_DOCKER)


def _kubeconform(text):
    """-> (rc, combined output). A TimeoutExpired propagates: a failure."""
    done = subprocess.run(KUBECONFORM_CMD, input=text.encode("ascii"),
                          capture_output=True, timeout=300)
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", "replace")


def _stream(texts):
    return "---\n".join(texts)


def _scratch_dir(test):
    os.makedirs(SCRATCH, exist_ok=True)
    path = tempfile.mkdtemp(dir=SCRATCH)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class YamlQuoteTest(unittest.TestCase):
    def test_hostile_values_round_trip(self):
        hostile = ["a: b", "x # y", "it's", 'say "hi"', "line1\nline2", "-lead",
                   "*star", "&anchor", "!tag", "{flow}", "[seq]", "",
                   "$HOME ${X}", "tab\there", "\x07bell", "\x7fdel", "é",
                   " ", "\U0001f600", "back\\slash"]
        for value in hostile:
            with self.subTest(value=value):
                quoted = yaml_quote(value)
                self.assertTrue(quoted.startswith('"') and quoted.endswith('"'))
                self.assertTrue(quoted.isascii())
                self.assertEqual(codecs.decode(quoted[1:-1], "unicode_escape"),
                                 value)

    def test_escapes_match_literal_expected_strings(self):
        self.assertEqual(yaml_quote('say "hi"'), '"say \\"hi\\""')
        self.assertEqual(yaml_quote("a\\b"), '"a\\\\b"')
        self.assertEqual(yaml_quote("a\nb"), '"a\\nb"')
        self.assertEqual(yaml_quote("\u00e9"), '"\\xe9"')

    def test_empty_string_is_two_quotes(self):
        self.assertEqual(yaml_quote(""), '""')

    def test_compose_quote_doubles_dollar(self):
        self.assertEqual(compose_quote("a$b"), '"a$$b"')


class ValidationHelpersTest(unittest.TestCase):
    def test_unknown_option_names_key_and_accepted_set(self):
        with self.assertRaises(GeneratorError) as ctx:
            check_options("compose", {"replicas": "2"}, COMPOSE_OPTIONS)
        self.assertIn("'replicas'", str(ctx.exception))
        self.assertIn("accepted: image, port", str(ctx.exception))

    def test_empty_option_value_is_refused(self):
        with self.assertRaises(GeneratorError) as ctx:
            check_options("compose", {"image": ""}, COMPOSE_OPTIONS)
        self.assertIn("must not be empty", str(ctx.exception))

    def test_empty_options_are_accepted(self):
        self.assertIsNone(check_options("compose", {}, COMPOSE_OPTIONS))

    def test_parse_port(self):
        self.assertEqual(parse_port("8000"), 8000)
        self.assertEqual(parse_port("65535"), 65535)
        for bad in ("0", "65536", "abc", "-1", ""):
            with self.subTest(bad=bad), self.assertRaises(GeneratorError):
                parse_port(bad)

    def test_parse_replicas(self):
        self.assertEqual(parse_replicas("1"), 1)
        for bad in ("0", "x", ""):
            with self.subTest(bad=bad), self.assertRaises(GeneratorError):
                parse_replicas(bad)

    def test_check_quantity(self):
        for good in ("100m", "0.5", "256Mi", "1Gi"):
            self.assertIsNone(check_quantity("cpu_request", good))
        for bad in ("lots", "1.", "10mi", ""):
            with self.subTest(bad=bad), self.assertRaises(GeneratorError):
                check_quantity("cpu_request", bad)

    def test_check_object_name(self):
        self.assertIsNone(check_object_name("pg-redis", "option"))
        self.assertIsNone(check_object_name("a" + "b" * 62, "option"))
        for bad in ("Pg-Redis", "Abc", "3tier", "9lives", "Bad_Name", "we:ird #x 'q'",
                    "a" + "b" * 63, "-x", "x-", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(GeneratorError) as ctx:
                    check_object_name(bad, "option")
                self.assertTrue(str(ctx.exception).startswith("--set name="))
        with self.assertRaises(GeneratorError) as ctx:
            check_object_name("9lives", "module")
        self.assertIn("taken from the source file name", str(ctx.exception))
        self.assertIn("--set name=<label>", str(ctx.exception))


class ClassifyCapabilitiesTest(unittest.TestCase):
    def test_postgres_redis_jwt_are_mapped(self):
        doc = {"nodes": [{"kind": "Capability", "name": n}
                         for n in ("postgres", "redis", "jwt")]}
        self.assertEqual(classify_capabilities(doc),
                         ({"postgres", "redis", "jwt"}, []))

    def test_http_capability_is_neither_mapped_nor_unknown(self):
        doc = {"nodes": [{"kind": "Capability", "name": "PaymentGateway",
                          "method": "post"}]}
        self.assertEqual(classify_capabilities(doc), (set(), []))

    def test_unknown_capability_is_listed_and_warned_once(self):
        doc = {"nodes": [{"kind": "Capability", "name": "postgres"},
                         {"kind": "Capability", "name": "foo"}]}
        mapped, unknown = classify_capabilities(doc)
        self.assertEqual((mapped, unknown), ({"postgres"}, ["foo"]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            warn_unknown("compose", unknown)
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("'foo'", lines[0])
        self.assertIn("lnpl generate compose", lines[0])

    def test_empty_document(self):
        self.assertEqual(classify_capabilities({"nodes": []}), (set(), []))

    def test_auth_env_var_must_be_a_valid_name(self):
        def doc(env):
            return {"nodes": [
                {"kind": "NetworkCall", "target": "Pay"},
                {"kind": "Capability", "name": "Pay", "method": "post",
                 "auth": {"kind": "bearer", "env": env}}]}
        with self.assertRaises(GeneratorError) as ctx:
            auth_env_vars(doc("BAD NAME"))
        self.assertIn("'BAD NAME'", str(ctx.exception))
        self.assertEqual(auth_env_vars(doc("PAY_TOKEN")), ["PAY_TOKEN"])
        self.assertEqual(endpoint_keys(doc("PAY_TOKEN")), ["LNPL_ENDPOINT_PAY"])


class HostileNetworkTargetTest(unittest.TestCase):
    """The compiler accepts `call foo:bar`; neither platform accepts the
    resulting `LNPL_ENDPOINT_FOO:BAR` key, so both generators refuse."""

    TARGETS = ("foo:bar", "\u00e9t\u00e9", "$dollar")

    def _doc(self, target):
        return {"module": "m", "nodes": [{"kind": "NetworkCall", "target": target}]}

    def test_both_generators_refuse_naming_the_target(self):
        for target in self.TARGETS:
            for generator in (generate_compose, generate_k8s):
                with self.subTest(target=target, generator=generator.__name__):
                    with self.assertRaises(GeneratorError) as ctx:
                        generator(self._doc(target), {})
                    self.assertIn(repr(target), str(ctx.exception))

    def test_refusal_leaves_out_untouched(self):
        out = _scratch_dir(self)
        for generator in (generate_compose, generate_k8s):
            with self.assertRaises(GeneratorError):
                run_generator(generator, self._doc("foo:bar"), {}, out)
        self.assertEqual(os.listdir(out), [])

    def test_a_normal_target_is_still_emitted(self):
        out, _ = _quiet(generate_k8s, self._doc("OrdersApi"), {})
        self.assertIn(b'"LNPL_ENDPOINT_ORDERSAPI"', out["k8s.yaml"])
        self.assertEqual(endpoint_keys(self._doc("OrdersApi")),
                         ["LNPL_ENDPOINT_ORDERSAPI"])


class ComposeGeneratorTest(unittest.TestCase):
    def test_goldens_match_byte_for_byte(self):
        for fixture in FIXTURES:
            with self.subTest(fixture=fixture):
                out, _ = _quiet(generate_compose, _doc(fixture), {})
                self.assertEqual(out["compose.yaml"],
                                 _golden(fixture, "compose.yaml"))

    def test_output_has_a_single_key_and_is_ascii(self):
        out, _ = _quiet(generate_compose, _doc("pg-redis"), {})
        self.assertEqual(list(out), ["compose.yaml"])
        self.assertIsInstance(out["compose.yaml"].decode("ascii"), str)

    def test_no_capabilities_emits_app_only(self):
        text = _text(generate_compose, "compose.yaml", "no-caps")
        for absent in ("\n  postgres:", "\n  redis:", "depends_on:", "\nvolumes:"):
            self.assertNotIn(absent, text)

    def test_postgres_and_redis_emit_backing_services(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis")
        self.assertIn("\n  postgres:\n", text)
        self.assertIn("\n  redis:\n", text)
        self.assertEqual(text.count("condition: service_healthy"), 2)

    def test_healthcheck_probes_readyz(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis")
        self.assertIn("urllib.request.urlopen('http://127.0.0.1:8000/-/readyz', "
                      "timeout=3)", text)
        self.assertNotIn("/-/healthz", text)

    def test_no_latest_tag_anywhere(self):
        for fixture in FIXTURES:
            with self.subTest(fixture=fixture):
                data = _golden(fixture, "compose.yaml")
                rest = data.replace(b"(no latest tag is published)", b"")
                self.assertNotIn(b"latest", rest)
                out, _ = _quiet(generate_compose, _doc(fixture), {})
                self.assertNotIn(
                    b"latest",
                    out["compose.yaml"].replace(b"(no latest tag is published)", b""))

    def test_env_keys_are_documented_or_named_secrets(self):
        documented = (
            "LNPL_SOURCE", "LNPL_BACKEND", "LNPL_JWT_SECRET_ENV",
            "LNPL_JWT_SECRET_FILE", "LNPL_CLOCK",
            "LNPL_ENDPOINT_<NAME>", "LNPL_LOG_FORMAT", "LNPL_TRACE_EXPORTER",
            "LNPL_IDEMPOTENCY_TTL_S", "LNPL_METRICS", "LNPL_CAPTURE_ON_FAILURE",
            "LNPL_TRUST_INCOMING_TRACE", "LNPL_RATE_LIMIT", "LNPL_CONFIG",
            "LNPL_PROFILE", "LNPL_CACHE", "LNPL_NETWORK", "LNPL_TOKEN_PROVIDER",
            "LNPL_JWT_ISSUER", "LNPL_AUDIT_SINK")
        with open(os.path.join(REPO, "docs", "serving.md"), encoding="utf-8") as fh:
            rows = [m.group(1) for m in
                    (re.match(r"^\| `(LNPL_[A-Z_<>]+)` \|", line) for line in fh)
                    if m]
        self.assertEqual(tuple(rows), documented)
        for fixture in FIXTURES:
            text = _text(generate_compose, "compose.yaml", fixture)
            for line in text.splitlines():
                m = re.match(r'^      "([A-Za-z_][A-Za-z0-9_]*)": ', line)
                if not m:
                    continue
                key = m.group(1)
                with self.subTest(fixture=fixture, key=key):
                    self.assertTrue(
                        key in documented or key.startswith("LNPL_ENDPOINT_")
                        or key in ("LNPL_JWT_SECRET", "POSTGRES_PASSWORD"))

    def test_jwt_http_endpoints_and_secret_reference(self):
        text = _text(generate_compose, "compose.yaml", "jwt-http")
        pay = '"LNPL_ENDPOINT_PAYMENTGATEWAY": "http://endpoint-placeholder.invalid"'
        orders = '"LNPL_ENDPOINT_ORDERSAPI": "http://endpoint-placeholder.invalid"'
        self.assertIn(pay, text)
        self.assertIn(orders, text)
        self.assertLess(text.index(pay), text.index(orders))
        self.assertIn('"LNPL_JWT_SECRET_ENV": "LNPL_JWT_SECRET"', text)
        self.assertIn("${LNPL_JWT_SECRET:?set LNPL_JWT_SECRET before docker "
                      "compose up}", text)

    def test_unknown_option_is_refused(self):
        with self.assertRaises(GeneratorError):
            generate_compose(_doc("pg-redis"), {"replicas": "2"})

    def test_bad_port_is_refused(self):
        with self.assertRaises(GeneratorError):
            generate_compose(_doc("pg-redis"), {"port": "0"})

    def test_port_and_image_options_are_used(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis",
                     {"port": "9000", "image": "reg.example/linkly:0.9"})
        self.assertIn("127.0.0.1:9000:8000", text)
        self.assertIn('image: "reg.example/linkly:0.9"', text)
        self.assertNotIn("PLACEHOLDER: set the image", text)

    def test_hostile_image_is_escaped(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis",
                     {"image": HOSTILE_VALUE})
        lines = [ln for ln in text.splitlines() if ln.startswith("    image: ")]
        self.assertEqual(
            lines[0], "    image: " + yaml_quote(HOSTILE_VALUE.replace("$", "$$")))

    def test_auth_variable_is_a_reference_only(self):
        out, _ = _quiet(generate_compose, _doc_with_auth("PAY_TOKEN"), {})
        text = out["compose.yaml"].decode("ascii")
        self.assertIn('      "PAY_TOKEN": "${PAY_TOKEN:?set PAY_TOKEN before '
                      'docker compose up}"', text)

    def test_source_option_drops_the_placeholder_comment(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis",
                     {"source": "/srv/app.lnpl"})
        self.assertIn('        source: "/srv/app.lnpl"\n', text)
        self.assertNotIn("PLACEHOLDER: path of the .lnpl source", text)

    def test_shared_auth_variable_is_emitted_once(self):
        doc = {"nodes": [
            {"kind": "NetworkCall", "target": "A"},
            {"kind": "NetworkCall", "target": "B"},
            {"kind": "Capability", "name": "A", "method": "post",
             "auth": {"kind": "bearer", "env": "SHARED"}},
            {"kind": "Capability", "name": "B", "method": "post",
             "auth": {"kind": "bearer", "env": "SHARED"}}]}
        self.assertEqual(auth_env_vars(doc), ["SHARED"])

    def test_every_option_value_is_escaped(self):
        text = _text(generate_compose, "compose.yaml", "pg-redis",
                     {"source": HOSTILE_VALUE, "postgres_image": HOSTILE_VALUE,
                      "redis_image": HOSTILE_VALUE})
        quoted = yaml_quote(HOSTILE_VALUE.replace("$", "$$"))
        self.assertIn("        source: " + quoted + "\n", text)
        self.assertEqual(text.count("    image: " + quoted + "\n"), 2)

    def test_hostile_module_is_not_emitted(self):
        doc = dict(_doc("pg-redis"), module="we:ird #x 'q'")
        out, _ = _quiet(generate_compose, doc, {})
        self.assertNotIn(b"we:ird", out["compose.yaml"])


class K8sGeneratorTest(unittest.TestCase):
    def test_goldens_match_byte_for_byte(self):
        for fixture in FIXTURES:
            with self.subTest(fixture=fixture):
                out, _ = _quiet(generate_k8s, _doc(fixture), {})
                self.assertEqual(out["k8s.yaml"], _golden(fixture, "k8s.yaml"))

    def test_kinds_are_configmap_deployment_service(self):
        for fixture in FIXTURES:
            text = _text(generate_k8s, "k8s.yaml", fixture)
            kinds = re.findall(r"^kind: (\w+)$", text, re.M)
            self.assertEqual(kinds, ["ConfigMap", "Deployment", "Service"])
            self.assertNotIn("kind: Secret", text)
            self.assertNotIn("stringData", text)

    def test_probes_and_grace_period(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis")
        self.assertLess(text.index("livenessProbe:"), text.index('path: "/-/healthz"'))
        self.assertLess(text.index('path: "/-/healthz"'), text.index("readinessProbe:"))
        self.assertLess(text.index("readinessProbe:"), text.index('path: "/-/readyz"'))
        self.assertEqual(text.count("terminationGracePeriodSeconds: 30"), 1)

    def test_grace_period_matches_serve_default(self):
        args = cli._build_parser().parse_args(["serve", "x.lnpl"])
        self.assertEqual(GRACE_PERIOD_S, args.grace_period)

    def test_no_capabilities_has_no_secret_refs(self):
        text = _text(generate_k8s, "k8s.yaml", "no-caps")
        self.assertNotIn("secretKeyRef:", text)
        self.assertNotIn("\n          env:\n", text)
        data = text.split("\ndata:\n", 1)[1].split("---", 1)[0]
        self.assertEqual(data, '  "LNPL_SOURCE": "/srv/lnpl/app.lnpl"\n')

    def test_secret_refs_by_name_only(self):
        pg = _text(generate_k8s, "k8s.yaml", "pg-redis")
        self.assertEqual(re.findall(r'key: "(\w+)"', pg),
                         ["LNPL_BACKEND", "LNPL_CACHE"])
        self.assertEqual(pg.count('name: "pg-redis-secrets"'), 2)
        jwt = _text(generate_k8s, "k8s.yaml", "jwt-http")
        self.assertIn('key: "LNPL_JWT_SECRET"', jwt)
        self.assertIn('"LNPL_JWT_SECRET_ENV": "LNPL_JWT_SECRET"', jwt)

    def test_auth_variable_is_a_secret_ref_after_jwt(self):
        out, _ = _quiet(generate_k8s, _doc_with_auth("PAY_TOKEN"), {})
        text = out["k8s.yaml"].decode("ascii")
        self.assertEqual(re.findall(r'key: "(\w+)"', text),
                         ["LNPL_JWT_SECRET", "PAY_TOKEN"])

    def test_defaults_are_visible_placeholders(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis")
        self.assertIn("  replicas: 1\n", text)
        self.assertIn("# PLACEHOLDER: replica count is not known to the "
                      "generator; set with --set replicas=N.", text)
        self.assertIn("# PLACEHOLDER: set the image with --set image=", text)
        self.assertIn("# PLACEHOLDER: no resources set (BestEffort QoS)", text)
        self.assertNotIn("resources:", text)

    def test_resources_from_options(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis",
                     {"cpu_request": "250m", "cpu_limit": "500m",
                      "memory": "256Mi"})
        self.assertIn("          resources:\n"
                      "            requests:\n"
                      '              cpu: "250m"\n'
                      '              memory: "256Mi"\n'
                      "            limits:\n"
                      '              cpu: "500m"\n'
                      '              memory: "256Mi"\n', text)
        self.assertNotIn("PLACEHOLDER: no resources", text)

    def test_replicas_option_is_written_and_drops_the_placeholder(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"replicas": "3"})
        self.assertIn("  replicas: 3\n", text)
        self.assertNotIn("PLACEHOLDER: replica count", text)

    def test_only_cpu_limit_emits_a_limits_map_only(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"cpu_limit": "1"})
        self.assertIn('            limits:\n              cpu: "1"\n', text)
        self.assertNotIn("requests:", text)

    def test_only_cpu_request_emits_a_requests_map_only(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"cpu_request": "250m"})
        self.assertIn('            requests:\n              cpu: "250m"\n', text)
        self.assertNotIn("limits:", text)
        self.assertNotIn("PLACEHOLDER: no resources", text)

    def test_image_option_drops_the_placeholder_comment(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"image": "r/a:1"})
        self.assertNotIn("PLACEHOLDER: set the image", text)

    def test_bad_options_are_refused(self):
        for options in ({"cpu_limit": "lots"}, {"memory": "10mi"},
                        {"replicas": "0"}, {"cpu_request": "lots"},
                        {"port": "8000"}, {"image": ""}):
            with self.subTest(options=options), self.assertRaises(GeneratorError):
                generate_k8s(_doc("pg-redis"), options)

    def test_name_rule(self):
        for bad in ("Bad_Name", "3tier", "a" + "b" * 63):
            with self.subTest(name=bad):
                with self.assertRaises(GeneratorError) as ctx:
                    generate_k8s(_doc("pg-redis"), {"name": bad})
                self.assertTrue(str(ctx.exception).startswith("--set name="))
        longest = "a" + "b" * 62
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"name": longest})
        self.assertIn('name: "%s"' % longest, text)

    def test_module_name_rule(self):
        path = os.path.join(_scratch_dir(self), "9lives.lnpl")
        shutil.copyfile(os.path.join(GOLDEN, "pg-redis.lnpl"), path)
        doc = cli.compile_source([path])
        with self.assertRaises(GeneratorError) as ctx:
            generate_k8s(doc, {})
        self.assertIn("'9lives'", str(ctx.exception))
        self.assertIn("taken from the source file name", str(ctx.exception))
        out = generate_k8s(doc, {"name": "nine-lives"})
        self.assertIn(b'name: "nine-lives"', out["k8s.yaml"])

    def test_hostile_module_needs_name_option(self):
        doc = dict(_doc("pg-redis"), module="we:ird #x 'q'")
        with self.assertRaises(GeneratorError):
            generate_k8s(doc, {})
        out, _ = _quiet(generate_k8s, doc, {"name": "weird"})
        self.assertNotIn(b"we:ird", out["k8s.yaml"])

    def test_hostile_image_is_escaped(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"image": HOSTILE_VALUE})
        lines = [ln for ln in text.splitlines()
                 if ln.startswith("          image: ")]
        self.assertEqual(lines, ["          image: " + yaml_quote(HOSTILE_VALUE)])


class K8sIngressTest(unittest.TestCase):
    """Issue #236 D13: `--set ingress_host=<host>`."""

    def test_normal_ingress_routes_each_service_segment(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis",
                     {"ingress_host": "api.example.com"})
        self.assertEqual(_kinds(text), ["ConfigMap", "Deployment", "Service", "Ingress"])
        self.assertIn('host: "api.example.com"', text)
        ingress = _documents(text)[-1]
        self.assertEqual(ingress.count('path: "/note-service"'), 1)
        self.assertIn('pathType: "Prefix"', ingress)
        self.assertNotIn('path: "/"\n', ingress)
        self.assertNotIn('"/-/', ingress)

    def test_error_bad_hosts_are_refused(self):
        for host in ("Bad Host", "-api.example.com", "api.example.com/x",
                     "api.example.com\n",
                     ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 62])):
            with self.subTest(host=host):
                with self.assertRaises(GeneratorError) as cm:
                    _quiet(generate_k8s, _doc("pg-redis"), {"ingress_host": host})
                self.assertIn("ingress_host", str(cm.exception))

    def test_boundary_253_character_host_is_accepted(self):
        host = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
        self.assertEqual(len(host), 253)
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"ingress_host": host})
        self.assertIn("host: " + yaml_quote(host), text)

    def test_error_no_served_path(self):
        with mock.patch("lnpl.deploy_gen.build_routes", return_value={}):
            with self.assertRaises(GeneratorError) as cm:
                _quiet(generate_k8s, _doc("pg-redis"), {"ingress_host": "api.example.com"})
        self.assertIn("serves no path", str(cm.exception))
        with mock.patch("lnpl.deploy_gen.build_routes", side_effect=ServeError("boom")):
            with self.assertRaises(GeneratorError) as cm:
                _quiet(generate_k8s, _doc("pg-redis"), {"ingress_host": "api.example.com"})
        self.assertIn("boom", str(cm.exception))

    def test_boundary_absent_option_emits_no_ingress(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis")
        self.assertNotIn("kind: Ingress", text)

    def test_signature_and_option_order_are_frozen(self):
        self.assertEqual(list(inspect.signature(generate_k8s).parameters),
                         ["document", "options"])
        self.assertEqual(K8S_OPTIONS[:6], ("image", "name", "replicas", "cpu_request",
                                           "cpu_limit", "memory"))

    def test_every_k8s_option_is_in_the_set_help(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["generate", "--help"])
        help_text = " ".join(out.getvalue().split())
        for key in K8S_OPTIONS:
            with self.subTest(key=key):
                self.assertIn(key, help_text)


class K8sHpaTest(unittest.TestCase):
    """Issue #236 D14: `hpa_min`, `hpa_max`, `hpa_cpu` (with `cpu_request`)."""

    GOOD = {"hpa_min": "2", "hpa_max": "5", "hpa_cpu": "70", "cpu_request": "100m"}

    def test_normal_hpa_emitted_and_replicas_dropped(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", self.GOOD)
        self.assertIn("minReplicas: 2", text)
        self.assertIn("maxReplicas: 5", text)
        self.assertIn("averageUtilization: 70", text)
        self.assertIn('cpu: "100m"', text)
        deployment = _documents(text)[1]
        self.assertIn("kind: Deployment", deployment)
        self.assertNotIn("replicas:", deployment)
        self.assertNotIn("PLACEHOLDER: replica count", deployment)
        self.assertEqual(_kinds(text)[-1], "HorizontalPodAutoscaler")

    def test_normal_leading_zero_is_reserialised(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", dict(self.GOOD, hpa_min="02"))
        hpa = _documents(text)[-1].splitlines()
        self.assertIn("kind: HorizontalPodAutoscaler", hpa)
        self.assertIn("  minReplicas: 2", hpa)
        self.assertEqual([ln for ln in hpa if "02" in ln], [])

    def test_error_cases_name_the_key(self):
        cases = [
            (dict(self.GOOD, hpa_min="3", hpa_max="2"), "hpa_max"),
            ({"hpa_min": "2", "cpu_request": "100m"}, "hpa_max"),
            (dict(self.GOOD, hpa_cpu="0"), "hpa_cpu"),
            (dict(self.GOOD, hpa_cpu="101"), "hpa_cpu"),
            (dict(self.GOOD, hpa_min="0"), "hpa_min"),
            (dict(self.GOOD, hpa_min="two"), "hpa_min"),
            (dict(self.GOOD, hpa_min="2\n"), "hpa_min"),
            ({k: v for k, v in self.GOOD.items() if k != "cpu_request"}, "cpu_request"),
            (dict(self.GOOD, replicas="3"), "replicas"),
        ]
        for options, key in cases:
            with self.subTest(options=options):
                with self.assertRaises(GeneratorError) as cm:
                    _quiet(generate_k8s, _doc("pg-redis"), options)
                self.assertIn(key, str(cm.exception))

    def test_boundary_min_equals_max_and_cpu_100(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis",
                     {"hpa_min": "1", "hpa_max": "1", "hpa_cpu": "100", "cpu_request": "1"})
        self.assertIn("minReplicas: 1", text)
        self.assertIn("maxReplicas: 1", text)
        self.assertIn("averageUtilization: 100", text)


class K8sPdbTest(unittest.TestCase):
    """Issue #236 D15: `pdb=true`."""

    def test_normal_pdb_true(self):
        from lnpl.deploy_gen import _PDB_COMMENT
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"pdb": "true"})
        self.assertIn("kind: PodDisruptionBudget", text)
        self.assertIn("minAvailable: 1", text)
        lines = text.splitlines()
        at = lines.index("apiVersion: policy/v1")
        self.assertEqual(lines[at - 1], _PDB_COMMENT)

    def test_error_other_literals_refused(self):
        for value in ("yes", "True", "1", "on"):
            with self.subTest(value=value):
                with self.assertRaises(GeneratorError) as cm:
                    _quiet(generate_k8s, _doc("pg-redis"), {"pdb": value})
                self.assertIn("pdb", str(cm.exception))

    def test_boundary_false_and_absent_emit_nothing(self):
        false_out, _ = _quiet(generate_k8s, _doc("pg-redis"), {"pdb": "false"})
        absent_out, _ = _quiet(generate_k8s, _doc("pg-redis"), {})
        self.assertNotIn(b"PodDisruptionBudget", false_out["k8s.yaml"])
        self.assertNotIn(b"PodDisruptionBudget", absent_out["k8s.yaml"])
        self.assertEqual(false_out["k8s.yaml"], absent_out["k8s.yaml"])


class K8sNetworkPolicyTest(unittest.TestCase):
    """Issue #236 D16-D18: `network_policy=true`, `egress_cidrs`."""

    def test_normal_policy_with_cidrs(self):
        from lnpl.deploy_gen import _NETPOL_COMMENTS
        text = _text(generate_k8s, "k8s.yaml", "pg-redis",
                     {"network_policy": "true",
                      "egress_cidrs": "203.0.113.0/24,2001:db8::/32"})
        self.assertEqual(text.count("ipBlock:"), 2)
        self.assertEqual(text.count('"k8s-app": "kube-dns"'), 1)
        self.assertIn('cidr: "203.0.113.0/24"', text)
        self.assertIn('cidr: "2001:db8::/32"', text)
        lines = text.splitlines()
        at = lines.index("apiVersion: networking.k8s.io/v1")
        self.assertEqual(lines[at - 3:at], _NETPOL_COMMENTS)
        policy = _documents(text)[-1]
        self.assertIn("kind: NetworkPolicy", policy)
        self.assertIn('- "Ingress"', policy)
        self.assertIn('- "Egress"', policy)
        self.assertIn("port: 8000", policy)
        self.assertNotIn("from:", policy)

    def test_boundary_policy_alone_has_dns_rule_only(self):
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", {"network_policy": "true"})
        self.assertEqual(_kinds(text).count("NetworkPolicy"), 1)
        self.assertNotIn("ipBlock:", text)
        self.assertIn('protocol: "UDP"\n          port: 53', text)
        self.assertIn('protocol: "TCP"\n          port: 53', text)
        text = _text(generate_k8s, "k8s.yaml", "pg-redis",
                     {"network_policy": "true", "egress_cidrs": "10.0.0.0/8"})
        self.assertEqual(text.count("ipBlock:"), 1)

    def test_error_bad_cidrs_name_the_item(self):
        for value, item in (("203.0.113.0", "'203.0.113.0'"),
                            ("not-a-cidr", "'not-a-cidr'"),
                            ("10.0.0.1/8", "'10.0.0.1/8'"),
                            ("203.0.113.0/24,,10.0.0.0/8", "''"),
                            ("203.0.113.0/24, 10.0.0.0/8", "' 10.0.0.0/8'")):
            with self.subTest(value=value):
                with self.assertRaises(GeneratorError) as cm:
                    _quiet(generate_k8s, _doc("pg-redis"),
                           {"network_policy": "true", "egress_cidrs": value})
                self.assertIn("egress_cidrs", str(cm.exception))
                self.assertIn(item, str(cm.exception))

    def test_error_cidrs_without_policy(self):
        with self.assertRaises(GeneratorError) as cm:
            _quiet(generate_k8s, _doc("pg-redis"), {"egress_cidrs": "10.0.0.0/8"})
        self.assertIn("network_policy=true", str(cm.exception))
        with self.assertRaises(GeneratorError) as cm:
            _quiet(generate_k8s, _doc("pg-redis"), {"network_policy": "on"})
        self.assertIn("network_policy", str(cm.exception))


class K8sAllOptionsTest(unittest.TestCase):
    def test_all_options_kind_order_and_shape(self):
        out, _ = _quiet(generate_k8s, _doc("pg-redis"), ALL_OPTIONS)
        self.assertEqual(list(out), ["k8s.yaml"])
        text = out["k8s.yaml"].decode("ascii")
        self.assertEqual(_kinds(text), ["ConfigMap", "Deployment", "Service", "Ingress",
                                        "HorizontalPodAutoscaler", "PodDisruptionBudget",
                                        "NetworkPolicy"])


class KubeconformTest(unittest.TestCase):
    """Issue #236 D20/D21: every generated document through the pinned
    kubeconform container; skips (or fails under LNPL_REQUIRE_KUBECONFORM=1)
    only when docker does not answer."""

    def test_every_generated_document_validates(self):
        _require_kubeconform(self)
        texts = [_text(generate_k8s, "k8s.yaml", f) for f in FIXTURES]
        texts.append(_text(generate_k8s, "k8s.yaml", "pg-redis", ALL_OPTIONS))
        stream = _stream(texts)
        self.assertEqual(len(re.findall(r"^kind: ", stream, re.M)), 19)
        rc, out = _kubeconform(stream)
        self.assertEqual(rc, 0, out)
        self.assertIn("Valid: 19, Invalid: 0, Errors: 0, Skipped: 0", out, out)

    def test_known_bad_hpa_is_invalid(self):
        _require_kubeconform(self)
        text = _text(generate_k8s, "k8s.yaml", "pg-redis", ALL_OPTIONS)
        hpa = [d for d in _documents(text) if "kind: HorizontalPodAutoscaler" in d]
        self.assertEqual(len(hpa), 1)
        lines = hpa[0].splitlines()
        self.assertIn("  maxReplicas: 5", lines)
        lines.remove("  maxReplicas: 5")
        rc, out = _kubeconform("\n".join(lines) + "\n")
        self.assertEqual(rc, 1, out)
        self.assertIn("Invalid: 1, Errors: 0", out, out)

    def test_docker_absent_skips_or_fails(self):
        with mock.patch("shutil.which", return_value=None), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LNPL_REQUIRE_KUBECONFORM", None)
            with self.assertRaises(unittest.SkipTest) as cm:
                _require_kubeconform(self)
            self.assertIn(KUBECONFORM_IMAGE, str(cm.exception))
            os.environ["LNPL_REQUIRE_KUBECONFORM"] = "1"
            with self.assertRaises(AssertionError) as cm:
                _require_kubeconform(self)
            self.assertIn(KUBECONFORM_IMAGE, str(cm.exception))

    def test_docker_info_timeout_or_failure_skips(self):
        with mock.patch("shutil.which", return_value="/usr/local/bin/docker"), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LNPL_REQUIRE_KUBECONFORM", None)
            with mock.patch("subprocess.run",
                            side_effect=subprocess.TimeoutExpired("docker", 20)):
                with self.assertRaises(unittest.SkipTest):
                    _require_kubeconform(self)
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                    ["docker", "info"], 1)):
                with self.assertRaises(unittest.SkipTest):
                    _require_kubeconform(self)


class UnknownCapabilityWarningTest(unittest.TestCase):
    def test_compose_warns_once_and_skips(self):
        out, err = _quiet(generate_compose, _doc("unknown-cap"), {})
        lines = [ln for ln in err.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("'foo'", lines[0])
        self.assertIn("lnpl generate compose", lines[0])
        self.assertIn(b"\n  postgres:\n", out["compose.yaml"])
        self.assertNotIn(b"foo", out["compose.yaml"])

    def test_a_repeated_unknown_capability_warns_once(self):
        doc = {"nodes": [{"kind": "Capability", "name": "foo"},
                         {"kind": "Capability", "name": "foo"}]}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            warn_unknown("compose", classify_capabilities(doc)[1])
        self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_k8s_warns_once_and_skips(self):
        out, err = _quiet(generate_k8s, _doc("unknown-cap"), {})
        lines = [ln for ln in err.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("'foo'", lines[0])
        self.assertIn("lnpl generate k8s", lines[0])
        self.assertNotIn(b"foo", out["k8s.yaml"])


class _DeployTCK(GeneratorTCK):
    GENERATE = None

    def make_generator(self):
        return self.GENERATE

    def make_document(self):
        return _doc("pg-redis")

    def make_out_dir(self):
        return _scratch_dir(self)


class ComposeGeneratorTCKTest(_DeployTCK, unittest.TestCase):
    GENERATE = staticmethod(generate_compose)


class K8sGeneratorTCKTest(_DeployTCK, unittest.TestCase):
    GENERATE = staticmethod(generate_k8s)


if __name__ == "__main__":
    unittest.main()
