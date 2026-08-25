#!/usr/bin/env python3
"""gen_scale_corpus.py — synthetic `.lnpl` corpus generator (issue #117, t117 Task 01).

Generates a deterministic set of compilable `.lnpl` files spread across five
domain directories, modeling realistic naming rather than a single shared
word pool:

- Most entities in a domain get a **domain-specific noun** drawn from a list
  that grows with N (`DOMAIN_NOUNS`) — these never collide across domains by
  construction, the same way real domain-specific technical vocabulary
  (`Invoice`, `Shipment`, `Sku`, ...) rarely does.
- A minority of entities per domain (`SHARED_DRAW_FRACTION`, see below) get a
  name drawn from a small **shared common-noun pool** (`SHARED_NOUNS`) that
  different domains independently reuse — modeling the real phenomenon this
  measurement targets: independent teams occasionally reaching for the same
  generic word (`Order`, `Item`, `Status`, `Event`).

r1 review (F1): an earlier version drew every entity's name from one fixed
10-word pool with replacement, so `collision_events >= N - 10` was pigeonhole
arithmetic independent of any property of linkly — a namespace-free
codebase with realistic, non-repeating domain vocabulary would have produced
the same floor. This version reports pool sizes and the shared/unique split
alongside the collision count so the number is interpretable rather than a
generator-parameter artifact.

Pass --disambiguate to force every entity name globally unique (prefixed
with its domain + a zero-padded global index) when a compilable corpus is
needed instead.

Usage:
    gen_scale_corpus.py --entities N --out DIR [--seed S] [--disambiguate]
"""

import argparse
import os
import random
import sys

DOMAINS = ["billing", "shipping", "catalog", "identity", "support"]

# Small pool of genuinely generic, cross-domain vocabulary — the words
# different independently-authored domains might plausibly both reach for.
SHARED_NOUNS = ["Order", "Item", "Status", "Event"]

# Domain-specific technical vocabulary — 20 nouns per domain gives headroom
# up to 20 entities/domain (100 entities total at 5 domains), covering this
# measurement's tested scales (10/30/50) and the documented re-measurement
# point (100). Never repeated within a domain, and chosen not to overlap
# SHARED_NOUNS or each other's domain list, so any observed name collision
# in the non-disambiguated corpus is, by construction, a collision that
# crosses a domain boundary via SHARED_NOUNS — not an accident of a small
# pool running dry.
DOMAIN_NOUNS = {
    "billing": [
        "Invoice", "Charge", "Refund", "LedgerEntry", "Statement",
        "PaymentPlan", "CreditNote", "DebitNote", "Adjustment",
        "Reconciliation", "TaxLine", "Discount", "Surcharge",
        "BillingCycle", "DunningNotice", "PaymentMethod", "Chargeback",
        "Settlement", "FeeSchedule", "ProrationEntry",
    ],
    "shipping": [
        "Shipment", "Carrier", "TrackingEvent", "DeliveryWindow",
        "Manifest", "PackingSlip", "FreightQuote", "Waybill",
        "ReturnLabel", "DropoffPoint", "RouteSegment",
        "CustomsDeclaration", "ShippingRate", "ParcelDimension",
        "HandoffLog", "DeliveryException", "ConsolidatedLoad",
        "LastMileHop", "ProofOfDelivery", "ShippingZone",
    ],
    "catalog": [
        "Product", "Sku", "PriceTier", "Variant", "Bundle", "Category",
        "Brand", "Attribute", "InventorySnapshot", "Listing",
        "MerchandisingRule", "ProductImage", "Taxonomy",
        "SupplierCatalog", "PricePoint", "ProductReview", "Assortment",
        "CatalogFeed", "SeasonalCollection", "DiscontinuationNotice",
    ],
    "identity": [
        "Account", "Credential", "Session", "Role", "Permission",
        "LoginAttempt", "PasswordReset", "MfaEnrollment", "ApiKey",
        "DeviceFingerprint", "ConsentRecord", "TrustedDevice",
        "AccessGrant", "IdentityVerification", "SsoBinding",
        "RecoveryCode", "ProfileAttribute", "DelegatedAccess",
        "SecurityQuestion", "AuditTrailEntry",
    ],
    "support": [
        "Ticket", "Case", "Escalation", "KnowledgeArticle", "SlaBreach",
        "CannedResponse", "CustomerFeedback", "ChatTranscript",
        "SupportQueue", "ResolutionNote", "SatisfactionSurvey",
        "IssueCategory", "EscalationPolicy", "AgentAssignment",
        "ContactAttempt", "FollowUpReminder", "TicketMerge",
        "SupportChannel", "PriorityLevel", "HandoffNote",
    ],
}

# Modeling assumption, stated plainly rather than left implicit: roughly a
# third of a domain's entities lean on generic/shared vocabulary, the rest
# use domain-specific technical terms. This is what makes the reported
# collision count a statement about *shared-vocabulary reuse*, not about
# how big the domain-specific lists happen to be.
SHARED_DRAW_FRACTION = 1.0 / 3.0

# Four read-family verbs (verbs.md — all `RepositoryCall`), each resolved to
# an entity the same way: the step's object must equal the entity name fully
# lowercased (impl/lnpl/lower.py `_resolve_entity`, `"".join(split_pascal(name))`,
# which for a plain alnum PascalName is identical to `name.lower()`).
STEP_VERBS = ["find", "load", "read", "list"]


def _domain_sizes(entities):
    """How many of `entities` land in each of the five domains (round-robin)."""
    return [len(range(d, entities, len(DOMAINS))) for d in range(len(DOMAINS))]


def _plan_nouns(entities, rng):
    """Assign one noun per entity index, domain-realistic (see module docstring).

    Returns (nouns, pool_report): `nouns[i]` is the noun for entity `i`;
    `pool_report` is a dict per domain with the pool sizes and split actually
    used, for the measurement report to cite (interpretability, r1 F1).
    """
    sizes = _domain_sizes(entities)
    pool_report = {}
    # Per-domain plan: which within-domain occurrence indices draw shared vs
    # domain-unique, and in what order — computed once per domain up front so
    # generation itself is a simple sequential consumption of these plans.
    domain_plan = {}
    for d, domain in enumerate(DOMAINS):
        size = sizes[d]
        shared_count = min(round(size * SHARED_DRAW_FRACTION), len(SHARED_NOUNS))
        unique_count = size - shared_count
        if unique_count > len(DOMAIN_NOUNS[domain]):
            raise ValueError(
                "domain %r needs %d unique nouns but only %d are defined — "
                "raise --entities less, or extend DOMAIN_NOUNS[%r]"
                % (domain, unique_count, len(DOMAIN_NOUNS[domain]), domain))
        shared_words = list(SHARED_NOUNS)
        rng.shuffle(shared_words)
        shared_draws = shared_words[:shared_count]
        unique_draws = list(DOMAIN_NOUNS[domain][:unique_count])
        # Shared draws first, then unique — order doesn't affect which words
        # are used, only which file gets which (cosmetic).
        domain_plan[domain] = shared_draws + unique_draws
        pool_report[domain] = {
            "size": size,
            "shared_pool_size": len(SHARED_NOUNS),
            "shared_drawn": shared_count,
            "domain_pool_size": len(DOMAIN_NOUNS[domain]),
            "unique_drawn": unique_count,
        }

    domain_cursor = {domain: 0 for domain in DOMAINS}
    nouns = []
    for i in range(entities):
        domain = DOMAINS[i % len(DOMAINS)]
        cursor = domain_cursor[domain]
        nouns.append(domain_plan[domain][cursor])
        domain_cursor[domain] = cursor + 1
    return nouns, pool_report


def _entity_name(domain, index, noun, disambiguate):
    if not disambiguate:
        return noun
    # D2: "접두사를 붙여 전역 유일하게 만든다" — domain + zero-padded global
    # index as a prefix. The index alone already guarantees global
    # uniqueness; the domain makes the prefix self-describing.
    return "%s%04d%s" % (domain.capitalize(), index, noun)


def _entity_source(entity_name, index):
    obj = entity_name.lower()
    lines = [
        "entity %s" % entity_name,
        "    field",
        "        id UUID",
        "        name Text",
        "",
    ]
    for verb in STEP_VERBS:
        wf_name = "Wf%04d%s" % (index, verb.capitalize())
        lines.append("workflow %s" % wf_name)
        lines.append("    %s %s" % (verb, obj))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def generate(entities, out_dir, seed=0, disambiguate=False):
    """Write `entities` `.lnpl` files under `out_dir`'s five domain dirs.

    Deterministic: the same (entities, seed, disambiguate) always produces
    byte-identical files — the only source of variation (which shared nouns
    land in which domain) comes from `random.Random(seed)` alone (never the
    global `random` module).

    Returns (written_paths, pool_report) — `pool_report` (see `_plan_nouns`)
    is what the measurement report cites so the collision count is
    interpretable rather than opaque (r1 F1).
    """
    if entities < 1:
        raise ValueError("--entities must be >= 1, got %d" % entities)

    rng = random.Random(seed)
    for domain in DOMAINS:
        os.makedirs(os.path.join(out_dir, domain), exist_ok=True)

    nouns, pool_report = _plan_nouns(entities, rng)

    written = []
    for i in range(entities):
        domain = DOMAINS[i % len(DOMAINS)]
        noun = nouns[i]
        entity_name = _entity_name(domain, i, noun, disambiguate)
        filename = "%04d_%s.lnpl" % (i, noun.lower())
        path = os.path.join(out_dir, domain, filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(_entity_source(entity_name, i))
        written.append(path)
    return written, pool_report


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate a synthetic .lnpl corpus at a given entity scale "
                     "(issue #117 namespace-pressure measurement).")
    ap.add_argument("--entities", type=int, required=True,
                     help="number of entities to generate (>= 1)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--seed", type=int, default=0,
                     help="RNG seed for deterministic generation (default 0)")
    ap.add_argument("--disambiguate", action="store_true",
                     help="prefix entity names with domain+index so the "
                          "generated corpus compiles as one module")
    args = ap.parse_args(argv)

    if args.entities < 1:
        print("gen_scale_corpus: --entities must be >= 1, got %d"
              % args.entities, file=sys.stderr)
        return 2

    written, pool_report = generate(args.entities, args.out, seed=args.seed,
                                     disambiguate=args.disambiguate)
    print("wrote %d entity file(s) under %s" % (len(written), args.out))
    for domain, info in pool_report.items():
        print("  %s: %d entities, %d/%d shared-pool, %d/%d domain-pool"
              % (domain, info["size"], info["shared_drawn"],
                 info["shared_pool_size"], info["unique_drawn"],
                 info["domain_pool_size"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
