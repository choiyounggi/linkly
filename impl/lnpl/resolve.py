"""Name resolution shared by every consumer that accepts a short IR name —
issue #151.

RFC-0033 makes "same short name, different namespace" a legal *non*-
collision, and both `lnpl migrate` and spec-block expectations compile a
whole directory, so a bare `Order` can name two different entities at once
(`billing.Order`, `shipping.Order`). Matching on `node["name"]` alone and
returning the first hit silently picks whichever happened to be declared
first — a wrong-entity read with no error and no log line, and the second
entity is not reachable under any spelling.

So accept the qualified name too, and when a bare name matches more than
one node, refuse and list the candidates rather than pick one: issue #147
D5's "does not guess, refuses" rule. A bare name that matches exactly one
node of the requested kind still resolves — an unqualified single-namespace
or pre-RFC-0033 layout behaves exactly as before.

`migrate._resolve_entity` (issue #147) is the model this generalizes: same
resolution order, now parameterized over `kind` so a third consumer does not
reintroduce the bug this module exists to prevent.
"""


def qualified_name(node):
    """`billing.Order` when the node carries a namespace, else `Order`.

    Same spelling `openapi._schema_name` puts in `components/schemas`, so the
    name a user reads out of a generated spec is the name that can be used
    to address the node unambiguously.
    """
    return ("%s.%s" % (node["namespace"], node["name"])
            if node.get("namespace") else node["name"])


class AmbiguousName(Exception):
    """A short name matches more than one node of the requested kind.

    Callers wrap this in their own error type (`MigrateError`, `SpecError`)
    — this module does not know, and must not know, which CLI surface is
    asking.
    """


def resolve_node(doc, kind, name):
    """Find the node of `kind` that `name` names, or refuse if ambiguous.

    Resolution order (issue #147's `_resolve_entity`, preserved exactly):
    1. Qualified-name exact match. More than one hit — `namespace + "." +
       name` is a plain concatenation, and nothing constrains either half
       against a literal dot, so two distinct nodes can share one qualified
       spelling (namespace `a.b` + `C`, and namespace `a` + `b.C`). They have
       distinct ids, so the compiler is right not to reject them — but no
       name can tell them apart, and picking one would be the same silent
       wrong-node selection this function exists to prevent. Refuse and name
       the ids.
    2. Exactly one qualified-name hit — return it.
    3. Bare-name match (ignoring namespace). More than one hit — refuse and
       name the qualified spellings.
    4. Exactly one bare-name hit — return it.
    5. No match — return `None`; the caller reports that as undeclared.
    """
    candidates = [n for n in doc.get("nodes", []) if n["kind"] == kind]
    exact = [n for n in candidates if qualified_name(n) == name]
    if len(exact) > 1:
        raise AmbiguousName(
            "%r is ambiguous — %s share that qualified name; rename one so "
            "it can be addressed"
            % (name, ", ".join(sorted(n["id"] for n in exact))))
    if exact:
        return exact[0]
    bare = [n for n in candidates if n["name"] == name]
    if len(bare) > 1:
        raise AmbiguousName(
            "%r is ambiguous across namespaces (%s) — name one of them "
            "exactly"
            % (name, ", ".join(sorted(qualified_name(n) for n in bare))))
    return bare[0] if bare else None
