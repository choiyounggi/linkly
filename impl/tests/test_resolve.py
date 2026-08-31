"""`resolve.qualified_name` / `resolve_node` — issue #151.

RFC-0033 makes "same short name, different namespace" a legal non-collision.
`migrate._resolve_entity` (issue #147) already refuses a short name that
matches more than one entity instead of guessing; these pin the same rule
in the shared, kind-generic module both `migrate.py` and `spec.py` now sit
on top of.
"""

import unittest

from lnpl.resolve import AmbiguousName, qualified_name, resolve_node

BILLING_ORDER = {"kind": "Entity", "id": "entity.billing.order",
                 "name": "Order", "namespace": "billing"}
SHIPPING_ORDER = {"kind": "Entity", "id": "entity.shipping.order",
                  "name": "Order", "namespace": "shipping"}
FLAT_WIDGET = {"kind": "Entity", "id": "entity.widget", "name": "Widget"}
ORDER_PLACED = {"kind": "Event", "id": "event.billing.orderplaced",
                "name": "OrderPlaced", "namespace": "billing"}
SHIP_ORDER_PLACED = {"kind": "Event", "id": "event.shipping.orderplaced",
                     "name": "OrderPlaced", "namespace": "shipping"}


def doc(*nodes):
    return {"lir_version": "0.1", "module": "t", "nodes": list(nodes)}


class ResolveNodeTest(unittest.TestCase):

    # (정상) 네임스페이스 없는 단일 엔티티는 짧은 이름으로 해석된다.
    def test_a_single_unnamespaced_entity_resolves_by_its_short_name(self):
        found = resolve_node(doc(FLAT_WIDGET), "Entity", "Widget")

        self.assertEqual(FLAT_WIDGET, found)

    # (정상) 동명 엔티티가 서로 다른 네임스페이스에 있으면 정규화 이름으로
    # 각각 정확히 해석된다.
    def test_qualified_names_reach_the_right_namespace(self):
        d = doc(BILLING_ORDER, SHIPPING_ORDER)

        self.assertEqual(BILLING_ORDER, resolve_node(d, "Entity", "billing.Order"))
        self.assertEqual(SHIPPING_ORDER, resolve_node(d, "Entity", "shipping.Order"))

    # (에러) 짧은 이름이 둘 이상에 걸리면 추측하지 않고 후보를 전부 나열해 거부한다.
    def test_an_ambiguous_short_name_lists_every_candidate(self):
        d = doc(BILLING_ORDER, SHIPPING_ORDER)

        with self.assertRaises(AmbiguousName) as ctx:
            resolve_node(d, "Entity", "Order")

        message = str(ctx.exception)
        self.assertIn("billing.Order", message)
        self.assertIn("shipping.Order", message)

    # (경계) 매치가 0건이면 예외가 아니라 None을 반환한다.
    def test_no_match_returns_none_not_an_exception(self):
        found = resolve_node(doc(FLAT_WIDGET), "Entity", "Order")

        self.assertIsNone(found)

    # (정상, kind 일반성) 같은 함수가 다른 kind에도 같은 규칙을 적용한다.
    def test_the_same_rule_applies_to_a_different_kind(self):
        d = doc(ORDER_PLACED, SHIP_ORDER_PLACED)

        self.assertEqual(ORDER_PLACED, resolve_node(d, "Event", "billing.OrderPlaced"))
        with self.assertRaises(AmbiguousName):
            resolve_node(d, "Event", "OrderPlaced")

    # (경계) namespace 키가 아예 없는 노드와 namespace=None인 노드는 같게 취급된다.
    def test_a_missing_namespace_key_and_an_explicit_none_are_equivalent(self):
        no_key = {"kind": "Entity", "id": "entity.a", "name": "A"}
        explicit_none = {"kind": "Entity", "id": "entity.b", "name": "B",
                         "namespace": None}

        self.assertEqual("A", qualified_name(no_key))
        self.assertEqual("B", qualified_name(explicit_none))
        self.assertEqual(no_key, resolve_node(doc(no_key), "Entity", "A"))
        self.assertEqual(explicit_none,
                         resolve_node(doc(explicit_none), "Entity", "B"))


if __name__ == "__main__":
    unittest.main()
