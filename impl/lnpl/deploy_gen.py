"""Built-in `compose` and `k8s` generators (issue #189).

Output is YAML text written without a YAML library (settled user decision:
the core runtime dependency stays jsonschema only). Every interpolated
scalar goes through `yaml_quote`; comments are fixed text and never carry an
interpolated value (the one exception is the k8s header, which names the
object name after it passed the DNS-1035 rule). See docs/backends.md
section 12.
"""

import re
import sys

from .drivers import _http_capabilities
from .generators import GeneratorError
from .wsgi import _network_targets

# The `lnpl serve --grace-period` default (30.0, cli.py) and gunicorn's
# `graceful_timeout` default 30 s (docs/serving.md "SIGTERM 그레이스풀 드레인").
GRACE_PERIOD_S = 30
# docker/Dockerfile `EXPOSE 8000`.
CONTAINER_PORT = 8000
SOURCE_PATH = "/srv/lnpl/app.lnpl"
IMAGE_PLACEHOLDER = "ghcr.io/OWNER/linkly:VERSION"
ENDPOINT_PLACEHOLDER = "http://endpoint-placeholder.invalid"
COMPOSE_OPTIONS = ("image", "port", "source", "postgres_image", "redis_image")
K8S_OPTIONS = ("image", "name", "replicas", "cpu_request", "cpu_limit", "memory")
MAPPED_CAPABILITIES = ("postgres", "redis", "jwt")

_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]*[a-z0-9])?$")
_NAME_MAX = 63
_QUANTITY_RE = re.compile(r"^[0-9]+(\.[0-9]+)?(m|k|M|G|T|P|E|Ki|Mi|Gi|Ti|Pi|Ei)?$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIGITS_RE = re.compile(r"^[0-9]+$")

_IMAGE_COMMENT = ("# PLACEHOLDER: set the image with "
                  "--set image=ghcr.io/<owner>/linkly:<X.Y> "
                  "(no latest tag is published).")
_ENDPOINT_COMMENT = "# PLACEHOLDER: base URL of this network target."


def yaml_quote(value):
    """`value` -> a YAML 1.2 double-quoted scalar, pure ASCII.

    Escapes follow https://yaml.org/spec/1.2.2/ section 5.7 (escaped
    characters): printable ASCII is written as is, every other code point
    as `\\xNN`, `\\uNNNN` or `\\UNNNNNNNN`."""
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif 0x20 <= code <= 0x7e:
            out.append(ch)
        elif code <= 0xff:
            out.append("\\x%02x" % code)
        elif code <= 0xffff:
            out.append("\\u%04x" % code)
        else:
            out.append("\\U%08x" % code)
    out.append('"')
    return "".join(out)


def compose_quote(value):
    """`yaml_quote` for a Compose value. Compose interpolates `$VAR` and
    `${VAR}`; `$$` is its literal-dollar escape (Compose spec, interpolation:
    https://github.com/compose-spec/compose-spec/blob/main/12-interpolation.md)."""
    return yaml_quote(value.replace("$", "$$"))


def check_options(generator_name, options, accepted):
    """Refuse an option key outside `accepted` and an empty value."""
    for key in sorted(options):
        if key not in accepted:
            raise GeneratorError(
                "unknown option %r for generator %r (accepted: %s)"
                % (key, generator_name, ", ".join(accepted)))
        if options[key] == "":
            raise GeneratorError(
                "option %r for generator %r must not be empty"
                % (key, generator_name))


def parse_port(value):
    if not _DIGITS_RE.match(value) or not 1 <= int(value) <= 65535:
        raise GeneratorError(
            "option 'port' must be an integer from 1 to 65535, got %r" % value)
    return int(value)


def parse_replicas(value):
    if not _DIGITS_RE.match(value) or int(value) < 1:
        raise GeneratorError(
            "option 'replicas' must be an integer of at least 1, got %r" % value)
    return int(value)


def check_quantity(key, value):
    if not _QUANTITY_RE.match(value):
        raise GeneratorError(
            "option %r must be a Kubernetes quantity such as 100m, 0.5 or "
            "256Mi, got %r" % (key, value))


def check_object_name(value, origin):
    """The one platform-name rule (DNS-1035 label). `origin` is "module" or
    "option"; the value is refused, never rewritten."""
    if _NAME_RE.match(value) and len(value) <= _NAME_MAX:
        return
    if origin == "module":
        raise GeneratorError(
            "module name %r (taken from the source file name) is not a "
            "DNS-1035 label (lowercase letter first, then lowercase letters, "
            "digits or '-', at most 63 characters); pass --set name=<label>"
            % value)
    raise GeneratorError(
        "--set name=%r is not a DNS-1035 label (lowercase letter first, then "
        "lowercase letters, digits or '-', at most 63 characters)" % value)


def classify_capabilities(document):
    """-> (mapped set, unknown list). An http capability (a node with a
    `method` key, as `drivers._http_capabilities` filters) is neither."""
    mapped = set()
    unknown = []
    for node in document["nodes"]:
        if node["kind"] != "Capability" or "method" in node:
            continue
        name = node["name"]
        if name in MAPPED_CAPABILITIES:
            mapped.add(name)
        elif name not in unknown:
            unknown.append(name)
    return mapped, unknown


def warn_unknown(generator_name, unknown):
    for name in unknown:
        print("lnpl generate %s: capability %r has no deployment mapping; "
              "skipped (mapped: postgres, redis, jwt, http <name>)"
              % (generator_name, name), file=sys.stderr)


def endpoint_keys(document):
    """`LNPL_ENDPOINT_<TARGET>` for every logical network target. The key is
    a mapping key and an env name, so it must satisfy the same rule as the
    auth variables (`_ENV_NAME_RE`); a target that cannot form one is refused
    (the compiler accepts such targets, the platform does not)."""
    keys = []
    for target in _network_targets(document):
        key = "LNPL_ENDPOINT_%s" % target.upper()
        if not _ENV_NAME_RE.match(key):
            raise GeneratorError(
                "network target %r cannot form an environment variable name "
                "(%r must match %s)" % (target, key, _ENV_NAME_RE.pattern))
        keys.append(key)
    return keys


def auth_env_vars(document):
    """Secret variables named by `capability http ... auth` of every logical
    network target, in target order, without duplicates."""
    caps = _http_capabilities(document)
    found = []
    for target in _network_targets(document):
        cap = caps.get(target)
        if not cap or not cap.get("auth"):
            continue
        var = cap["auth"]["env"]
        if not _ENV_NAME_RE.match(var):
            raise GeneratorError(
                "variable name %r (from capability http %s auth) is not a "
                "valid environment variable name" % (var, target))
        if var not in found:
            found.append(var)
    return found


def _finish(name, lines):
    return {name: ("\n".join(lines) + "\n").encode("ascii")}


def generate_compose(document, options):
    """-> {"compose.yaml": bytes} (docs/backends.md section 12)."""
    check_options("compose", options, COMPOSE_OPTIONS)
    image = options.get("image", IMAGE_PLACEHOLDER)
    port = parse_port(options.get("port", "8000"))
    source = options.get("source", "./app.lnpl")
    postgres_image = options.get("postgres_image", "postgres:16")
    redis_image = options.get("redis_image", "redis:7")

    mapped, unknown = classify_capabilities(document)
    warn_unknown("compose", unknown)
    endpoints = endpoint_keys(document)
    auth_vars = auth_env_vars(document)
    postgres = "postgres" in mapped
    redis = "redis" in mapped

    lines = [
        "# Generated by `lnpl generate compose` (issue #189). "
        "Re-run the generator instead of editing.",
        "# PLACEHOLDER lines mark values the generator cannot know; "
        "docs/backends.md section 12 lists every option.",
        "services:",
        "  app:",
    ]
    if "image" not in options:
        lines.append("    " + _IMAGE_COMMENT)
    lines += [
        "    image: " + compose_quote(image),
        "    ports:",
        "      - " + compose_quote("127.0.0.1:%d:%d" % (port, CONTAINER_PORT)),
        "    environment:",
        '      "LNPL_SOURCE": ' + yaml_quote(SOURCE_PATH),
    ]
    if "jwt" in mapped:
        lines += [
            '      "LNPL_JWT_SECRET_ENV": "LNPL_JWT_SECRET"',
            '      "LNPL_JWT_SECRET": "${LNPL_JWT_SECRET:?set LNPL_JWT_SECRET '
            'before docker compose up}"',
        ]
    for key in endpoints:
        lines.append("      " + _ENDPOINT_COMMENT)
        lines.append("      %s: %s" % (yaml_quote(key),
                                       yaml_quote(ENDPOINT_PLACEHOLDER)))
    for var in auth_vars:
        lines.append("      %s: %s" % (
            yaml_quote(var),
            yaml_quote("${%s:?set %s before docker compose up}" % (var, var))))
    if postgres:
        lines += [
            "      # PLACEHOLDER: the official image runs fake/sqlite only; "
            "with a derived image that installs lnpl-postgres, uncomment:",
            '      # "LNPL_BACKEND": "${LNPL_BACKEND:?set LNPL_BACKEND before '
            'docker compose up}"',
        ]
    if redis:
        lines += [
            "      # PLACEHOLDER: the official image has only the fake cache; "
            "with a derived image that installs a redis cache driver, "
            "uncomment:",
            '      # "LNPL_CACHE": "${LNPL_CACHE:?set LNPL_CACHE before '
            'docker compose up}"',
        ]
    lines.append("    volumes:")
    if "source" not in options:
        lines.append("      # PLACEHOLDER: path of the .lnpl source, relative "
                     "to this file; set with --set source=PATH.")
    lines += [
        "      - type: bind",
        "        source: " + compose_quote(source),
        "        target: " + yaml_quote(SOURCE_PATH),
        "        read_only: true",
        "    healthcheck:",
        '      test: ["CMD", "python", "-c", "import urllib.request; '
        "urllib.request.urlopen('http://127.0.0.1:8000/-/readyz', "
        'timeout=3)"]',
        "      interval: 5s",
        "      timeout: 5s",
        "      retries: 12",
        "      start_period: 10s",
    ]
    if postgres or redis:
        lines.append("    depends_on:")
        for service, present in (("postgres", postgres), ("redis", redis)):
            if present:
                lines += ["      %s:" % service,
                          "        condition: service_healthy"]
    if postgres:
        lines += [
            "  postgres:",
            "    image: " + compose_quote(postgres_image),
            "    environment:",
            '      "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:?set '
            'POSTGRES_PASSWORD before docker compose up}"',
            "    volumes:",
            '      - "postgres-data:/var/lib/postgresql/data"',
            "    healthcheck:",
            '      test: ["CMD", "pg_isready", "-U", "postgres"]',
            "      interval: 5s",
            "      timeout: 5s",
            "      retries: 12",
        ]
    if redis:
        lines += [
            "  redis:",
            "    image: " + compose_quote(redis_image),
            "    healthcheck:",
            '      test: ["CMD", "redis-cli", "ping"]',
            "      interval: 5s",
            "      timeout: 5s",
            "      retries: 12",
        ]
    if postgres:
        lines += ["volumes:", "  postgres-data: {}"]
    return _finish("compose.yaml", lines)


def generate_k8s(document, options):
    """-> {"k8s.yaml": bytes}: ConfigMap, Deployment, Service."""
    check_options("k8s", options, K8S_OPTIONS)
    if "name" in options:
        name = options["name"]
        check_object_name(name, "option")
    else:
        name = document["module"]
        check_object_name(name, "module")
    image = options.get("image", IMAGE_PLACEHOLDER)
    replicas = parse_replicas(options["replicas"]) if "replicas" in options else 1
    for key in ("cpu_request", "cpu_limit", "memory"):
        if key in options:
            check_quantity(key, options[key])

    mapped, unknown = classify_capabilities(document)
    warn_unknown("k8s", unknown)
    endpoints = endpoint_keys(document)
    secret_vars = []
    if "postgres" in mapped:
        secret_vars.append("LNPL_BACKEND")
    if "redis" in mapped:
        secret_vars.append("LNPL_CACHE")
    if "jwt" in mapped:
        secret_vars.append("LNPL_JWT_SECRET")
    secret_vars += auth_env_vars(document)

    q_name = yaml_quote(name)
    label = '"app.kubernetes.io/name": ' + q_name
    lines = [
        "# Generated by `lnpl generate k8s` (issue #189). "
        "Re-run the generator instead of editing.",
        '# Referenced, not generated: the ConfigMap "%s-source" holding '
        'app.lnpl, and the Secret "%s-secrets" when secretKeyRef entries '
        "exist. docs/backends.md section 12 has the kubectl create commands."
        % (name, name),
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        "  name: " + yaml_quote(name + "-config"),
        "  labels:",
        "    " + label,
        "data:",
        '  "LNPL_SOURCE": ' + yaml_quote(SOURCE_PATH),
    ]
    if "jwt" in mapped:
        lines.append('  "LNPL_JWT_SECRET_ENV": "LNPL_JWT_SECRET"')
    for key in endpoints:
        lines.append("  " + _ENDPOINT_COMMENT)
        lines.append("  %s: %s" % (yaml_quote(key),
                                   yaml_quote(ENDPOINT_PLACEHOLDER)))
    lines += [
        "---",
        "apiVersion: apps/v1",
        "kind: Deployment",
        "metadata:",
        "  name: " + q_name,
        "  labels:",
        "    " + label,
        "spec:",
    ]
    if "replicas" not in options:
        lines.append("  # PLACEHOLDER: replica count is not known to the "
                     "generator; set with --set replicas=N.")
    lines += [
        "  replicas: %d" % replicas,
        "  selector:",
        "    matchLabels:",
        "      " + label,
        "  template:",
        "    metadata:",
        "      labels:",
        "        " + label,
        "    spec:",
        "      terminationGracePeriodSeconds: %d" % GRACE_PERIOD_S,
        "      containers:",
        '        - name: "app"',
    ]
    if "image" not in options:
        lines.append("          " + _IMAGE_COMMENT)
    lines += [
        "          image: " + yaml_quote(image),
        "          ports:",
        '            - name: "http"',
        "              containerPort: %d" % CONTAINER_PORT,
        "          envFrom:",
        "            - configMapRef:",
        "                name: " + yaml_quote(name + "-config"),
    ]
    if secret_vars:
        lines.append("          env:")
        for var in secret_vars:
            lines += [
                "            - name: " + yaml_quote(var),
                "              valueFrom:",
                "                secretKeyRef:",
                "                  name: " + yaml_quote(name + "-secrets"),
                "                  key: " + yaml_quote(var),
            ]
    lines += [
        "          livenessProbe:",
        "            httpGet:",
        '              path: "/-/healthz"',
        '              port: "http"',
        "          readinessProbe:",
        "            httpGet:",
        '              path: "/-/readyz"',
        '              port: "http"',
    ]
    requests = [("cpu", options["cpu_request"])] if "cpu_request" in options else []
    limits = [("cpu", options["cpu_limit"])] if "cpu_limit" in options else []
    if "memory" in options:
        requests.append(("memory", options["memory"]))
        limits.append(("memory", options["memory"]))
    if not requests and not limits:
        lines.append("          # PLACEHOLDER: no resources set (BestEffort "
                     "QoS); measure, then set --set cpu_request=... "
                     "cpu_limit=... memory=...")
    else:
        lines.append("          resources:")
        for title, entries in (("requests", requests), ("limits", limits)):
            if entries:
                lines.append("            %s:" % title)
                for key, value in entries:
                    lines.append("              %s: %s" % (key, yaml_quote(value)))
    lines += [
        "          volumeMounts:",
        '            - name: "source"',
        '              mountPath: "/srv/lnpl"',
        "              readOnly: true",
        "      volumes:",
        '        - name: "source"',
        "          configMap:",
        "            name: " + yaml_quote(name + "-source"),
        "---",
        "apiVersion: v1",
        "kind: Service",
        "metadata:",
        "  name: " + q_name,
        "  labels:",
        "    " + label,
        "spec:",
        "  selector:",
        "    " + label,
        "  ports:",
        '    - name: "http"',
        "      port: %d" % CONTAINER_PORT,
        '      targetPort: "http"',
    ]
    return _finish("k8s.yaml", lines)
