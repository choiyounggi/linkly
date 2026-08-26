"""issue #127 (RFC-0035 SS D3): `security encrypt` is gone from the closed
vocabulary, not merely marked unenforced.

Binary proof that the mechanism was actually removed, not just dropped from
the enforcement matrix while the parser still accepted it: a source that
declares it must now fail to compile, and the compiler's own "allowed"
error must stop recommending the removed mechanism -- otherwise the
diagnostic would point an author at syntax that cannot compile.
"""

import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import parse

ENCRYPT_SOURCE = """
entity Account
    field
        id UUID
        cardNumber Password
service PaymentService
    security
        encrypt cardNumber
"""

SURVIVING_MECHANISMS_SOURCE = """
entity Account
    field
        id UUID
service PaymentService
    security
        jwt
        role admin
"""


class TestSecurityEncryptRemoved(unittest.TestCase):
    def test_a_source_declaring_encrypt_fails_to_compile(self):
        with self.assertRaises(LowerError):
            lower(parse(ENCRYPT_SOURCE), "t")

    def test_the_diagnostic_no_longer_recommends_encrypt(self):
        # The message legitimately NAMES the rejected token ("unknown
        # security mechanism 'encrypt'") -- that is test_the_error_names_
        # the_unknown_token below. What must not happen is the "(allowed:
        # ...)" clause still listing encrypt as something an author could
        # write instead.
        with self.assertRaises(LowerError) as ctx:
            lower(parse(ENCRYPT_SOURCE), "t")
        message = str(ctx.exception)
        self.assertIn("(allowed:", message)
        allowed_clause = message.split("(allowed:", 1)[1]
        self.assertNotIn("encrypt", allowed_clause)

    def test_the_error_names_the_unknown_token(self):
        # The error contract callers branch on: which token was rejected,
        # not just that something was.
        with self.assertRaises(LowerError) as ctx:
            lower(parse(ENCRYPT_SOURCE), "t")
        self.assertIn("encrypt", str(ctx.exception).split("(allowed:")[0])

    def test_the_surviving_mechanisms_still_compile(self):
        # Boundary: this removal is encrypt-only -- jwt and role (issue
        # #119's argument mechanism) must be unaffected.
        mod = lower(parse(SURVIVING_MECHANISMS_SOURCE), "t")
        self.assertIsNotNone(mod)


if __name__ == "__main__":
    unittest.main()
