"""Issues #218/#219 -- one Password-family judgement for `send`,
`emit ... with` and `call/request ... with`, taken over every entity that
declares the referenced name (RFC-0049 §3, RFC-0057 §3, RFC-0063 §1)."""
import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import parse

CAP_PATH = ('capability http PaymentGateway\n    method post\n'
            '    path "/pay/{}"\n\n')
CAP_NOPATH = 'capability http PaymentGateway\n    method post\n\n'
CUSTOMER = ('entity Customer\n    field\n        id UUID\n'
            '        secret Password\n        tier Text\n\n')
ORDER = 'entity Order\n    field\n        id UUID\n        secret Text\n\n'
GATE = 'entity Gate\n    field\n        id UUID\n        level Integer\n\n'
EVENT = 'event Pinged\n\n'
APIKEY = 'refine ApiKey of Password\n    minLength 8\n\n'
ACCOUNT = 'entity Account\n    field\n        id UUID\n        token ApiKey\n\n'
BOTH_ORDERS = (("customer-first", CUSTOMER + ORDER),
               ("order-first", ORDER + CUSTOMER))
PINNED_SEND_MESSAGE = (
    "workflow Ping: call/request send customer.secret has declared type "
    "Password, whose base is Password -- call/request must not surface a "
    "Password field in an outbound payload (issue #43's masking "
    "chokepoint: a masked field's value must never leave through an "
    "unmasked one)")


def workflow(*steps):
    return "workflow Ping\n" + "".join("    %s\n" % s for s in steps)


def compile_doc(source):
    return lower(parse(source), "m").to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


class _RefusalCase(unittest.TestCase):

    def refused(self, source):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(source)
        return str(ctx.exception)


class SameNameAcrossEntitiesTest(_RefusalCase):
    """#219: the verdict must not depend on entity declaration order."""

    def test_send_input_ref_is_refused_in_both_declaration_orders(self):
        for label, entities in BOTH_ORDERS:
            with self.subTest(order=label):
                msg = self.refused(CAP_NOPATH + entities + workflow(
                    "call PaymentGateway send input.secret as r"))
                self.assertIn("call/request send input.secret", msg)
                self.assertIn("Password (entity Customer)", msg)
                self.assertIn("outbound payload", msg)

    def test_emit_with_input_ref_is_refused_in_both_declaration_orders(self):
        for label, entities in BOTH_ORDERS:
            with self.subTest(order=label):
                msg = self.refused(CAP_NOPATH + entities + EVENT + workflow(
                    "emit pinged with input.secret"))
                self.assertIn("emit with input.secret", msg)
                self.assertIn("Password (entity Customer)", msg)

    def test_send_input_refinement_is_refused_naming_the_entity(self):
        msg = self.refused(CAP_NOPATH + APIKEY + ACCOUNT + workflow(
            "call PaymentGateway send input.token as r"))
        self.assertIn("call/request send input.token", msg)
        self.assertIn("ApiKey (entity Account)", msg)


class WithPathArgumentTest(_RefusalCase):
    """#218: a Password-family value must never be put into the URL path."""

    def test_call_with_input_password_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "call PaymentGateway with input.secret as r"))
        self.assertIn("call/request with input.secret", msg)
        self.assertIn("Password (entity Customer)", msg)
        self.assertIn("outbound request path", msg)

    def test_request_with_input_password_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "request PaymentGateway with input.secret as r"))
        self.assertIn("call/request with input.secret", msg)
        self.assertIn("outbound request path", msg)

    def test_with_input_password_is_refused_in_both_declaration_orders(self):
        for label, entities in BOTH_ORDERS:
            with self.subTest(order=label):
                msg = self.refused(CAP_PATH + entities + workflow(
                    "call PaymentGateway with input.secret as r"))
                self.assertIn("Password (entity Customer)", msg)

    def test_with_read_binding_password_field_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "find customer", "call PaymentGateway with customer.secret as r"))
        self.assertIn(
            "call/request with customer.secret has declared type Password, "
            "whose base is Password", msg)

    def test_with_unread_binding_password_field_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "call PaymentGateway with customer.secret as r"))
        self.assertIn("call/request with customer.secret", msg)

    def test_with_bare_password_name_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "call PaymentGateway with secret as r"))
        self.assertIn("call/request with secret", msg)
        self.assertIn("Password (entity Customer)", msg)

    def test_with_refinement_of_password_is_refused(self):
        msg = self.refused(CAP_PATH + APIKEY + ACCOUNT + workflow(
            "call PaymentGateway with input.token as r"))
        self.assertIn("ApiKey (entity Account)", msg)
        self.assertIn("Password", msg)

    def test_with_without_as_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + workflow(
            "call PaymentGateway with input.secret"))
        self.assertIn("call/request with input.secret", msg)

    def test_with_under_a_guard_is_refused(self):
        msg = self.refused(CAP_PATH + CUSTOMER + GATE + workflow(
            "when input.level > 0",
            "    call PaymentGateway with input.secret as r"))
        self.assertIn("call/request with input.secret", msg)


class UnchangedBehaviourTest(unittest.TestCase):
    """R4/R7/R8: everything that is not Password-family is untouched."""

    def test_non_password_references_compile_with_unchanged_ir(self):
        doc = compile_doc(CAP_PATH + CUSTOMER + EVENT + workflow(
            "call PaymentGateway send input.tier with input.id as r",
            "emit pinged with input.tier"))
        call = nodes_of(doc, "NetworkCall")[0]
        emit = nodes_of(doc, "EventEmit")[0]
        self.assertEqual(call["path_args"], ["input.id"])
        self.assertEqual(call["bodyMap"], [{"field": "tier", "ref": "input.tier"}])
        self.assertEqual(emit["payloadMap"], [{"field": "tier", "ref": "input.tier"}])

    def test_with_refs_without_a_declared_password_shape_still_compile(self):
        cases = {
            "undeclared input field": (
                ["call PaymentGateway with input.nope as r"], "input.nope"),
            "unknown binding": (
                ["call PaymentGateway with ghost.secret as r"], "ghost.secret"),
            "caller scope": (
                ["call PaymentGateway with caller.subject as r"], "caller.subject"),
            "network result": (
                ["call PaymentGateway with input.id as first",
                 "call PaymentGateway with first.secret as r"], "first.secret"),
        }
        for label, (steps, ref) in cases.items():
            with self.subTest(case=label):
                doc = compile_doc(CAP_PATH + CUSTOMER + workflow(*steps))
                self.assertEqual(nodes_of(doc, "NetworkCall")[-1]["path_args"], [ref])

    def test_send_binding_password_message_is_byte_identical(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(CAP_NOPATH + CUSTOMER + workflow(
                "find customer", "call PaymentGateway send customer.secret as r"))
        self.assertEqual(str(ctx.exception), PINNED_SEND_MESSAGE)


if __name__ == "__main__":
    unittest.main()
