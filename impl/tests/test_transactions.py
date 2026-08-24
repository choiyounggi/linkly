"""Workflow execution is a transaction boundary (issue #79, RFC-0032).

Before this, every write (`create`/`update`/`delete`/`persist`/the outbox
`record_emission` insert) committed individually — a workflow that failed on
its second write left the first one permanently on disk, and a failed run's
registered emission still survived in `lnpl_outbox` (the #102 carryover this
file also closes). `Interpreter.run_workflow` now opens one transaction per
execution: commit on `status == "completed"`, rollback on anything else.

`TransactionBoundaryTest` reuses `ContractTestCase` from
`test_driver_contract.py` — the same "one scenario, two drivers" harness —
because the claim under test is asymmetric by design: sqlite actually
discards a failed run's writes, while the Fake's `begin`/`commit`/`rollback`
stay no-op (RFC-0032 §Reference-level Specification, "드라이버 계약") and so
does NOT roll anything back. Both are the contract, not a bug in one of them.
"""

import unittest

from tests.test_driver_contract import BACKENDS, ContractTestCase

TWO_WRITES = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        status Text

workflow TwoWrites
    create product
    create order
"""

READ_ONLY_NO_WRITES = """entity Product
    field
        id UUID
        stock Integer

workflow ReadOnly
    read product
"""

EMIT_THEN_CONFLICT = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow EmitThenFail
    create order
    emit orderPlaced
    create order
"""

EMIT_ONLY = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
"""


class TransactionBoundaryTest(ContractTestCase):
    """RFC-0032 §Reference-level Specification, §실행 경계."""

    def test_a_completing_two_write_workflow_persists_both_writes(self):
        """정상: 워크플로가 끝까지 성공하면 두 쓰기 모두 영속된다."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                payload = {"id": "x-1"}

                result, _ = self.execute(TWO_WRITES, payload, backend,
                                         seed=False, repository=repository)

                self.assertEqual(result["status"], "completed")
                self.assertIsNotNone(repository.execute(
                    "entity.product", "read", "entity.product#x-1"))
                self.assertIsNotNone(repository.execute(
                    "entity.order", "read", "entity.order#x-1"))

    def test_sqlite_discards_the_first_write_when_the_second_fails(self):
        """에러 (DoD 핵심): 2번째 쓰기가 실패하면 1번째 쓰기가 sqlite에
        잔존하지 않는다. `entity.order`를 미리 심어 두 번째 `create order`가
        (`sqlite3.IntegrityError` -> `DriverError` -> `RunError`로) 자연스럽게
        충돌하게 만든다 — 첫 번째 쓰기(`create product`)는 그 전에 성공한다."""
        repository = self._repository("sqlite")
        payload = {"id": "x-1"}
        repository.seed({"entity.order": {"entity.order#x-1": {"id": "x-1"}}})

        result, _ = self.execute(TWO_WRITES, payload, "sqlite", seed=False,
                                 repository=repository)

        self.assertEqual(result["status"], "failed")
        self.assertIn("create conflicts", result["failure_reason"])
        self.assertIsNone(repository.execute(
            "entity.product", "read", "entity.product#x-1"))

    def test_fake_backend_keeps_the_first_write_by_its_no_op_contract(self):
        """경계: Fake의 `begin`/`commit`/`rollback`은 no-op이다(RFC-0032) —
        같은 실패에서도 이미 쓰인 첫 write는 그대로 남는다. 이것은 계약
        위반이 아니라 D2가 명시한 설계다."""
        repository = self._repository("fake")
        payload = {"id": "x-1"}
        repository.seed({"entity.order": {"entity.order#x-1": {"id": "x-1"}}})

        result, _ = self.execute(TWO_WRITES, payload, "fake", seed=False,
                                 repository=repository)

        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(repository.execute(
            "entity.product", "read", "entity.product#x-1"))

    def test_a_zero_write_workflow_still_opens_and_closes_the_boundary(self):
        """경계: 쓰기가 하나도 없는 워크플로에서도 begin()/commit()이
        정상 동작한다 — 빈 트랜잭션도 유효한 경계다."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                repository.seed({"entity.product":
                                 {"entity.product#p-1": {"id": "p-1", "stock": 3}}})

                result, _ = self.execute(READ_ONLY_NO_WRITES, {"id": "p-1"},
                                         backend, seed=False,
                                         repository=repository)

                self.assertEqual(result["status"], "completed")

    def test_a_rolled_back_sqlite_connection_runs_a_retry_cleanly(self):
        """경계: 롤백 후 같은 드라이버 인스턴스로 재실행하면 정상 동작한다
        — 연결이 열린 트랜잭션에 갇혀 남지 않는다(다음 begin()이 "cannot
        start a transaction within a transaction"으로 죽지 않는다)."""
        repository = self._repository("sqlite")
        repository.seed({"entity.order": {"entity.order#x-1": {"id": "x-1"}}})

        first, _ = self.execute(TWO_WRITES, {"id": "x-1"}, "sqlite",
                                seed=False, repository=repository)
        self.assertEqual(first["status"], "failed")

        second, _ = self.execute(TWO_WRITES, {"id": "y-1"}, "sqlite",
                                 seed=False, repository=repository)

        self.assertEqual(second["status"], "completed")
        self.assertIsNotNone(repository.execute(
            "entity.product", "read", "entity.product#y-1"))
        self.assertIsNotNone(repository.execute(
            "entity.order", "read", "entity.order#y-1"))


class OutboxTransactionalTest(ContractTestCase):
    """RFC-0032 §Reference-level Specification (EventEmit 행) + issue #102
    이월: 실패한 실행의 emission은 `lnpl_outbox`에 잔존하지 않는다."""

    def test_a_failed_run_leaves_no_outbox_row_on_sqlite(self):
        """에러 (#102 이월 DoD): `emit` 뒤에 같은 실행 안에서 세 번째 step이
        실패하면, 등록됐던 emission도 함께 롤백된다. 아무것도 미리 심지
        않는다 — `EMIT_THEN_CONFLICT`의 세 번째 `create order`는 첫 번째
        step이 이번 실행에서 방금 만든 바로 그 행과 자연스럽게 충돌한다."""
        repository = self._repository("sqlite")
        payload = {"id": "o-1"}

        result, interp = self.execute(EMIT_THEN_CONFLICT, payload, "sqlite",
                                      seed=False, repository=repository)

        self.assertEqual(result["status"], "failed")
        # The interpreter's in-memory bookkeeping still reports the attempted
        # emission — that contract (spec's `emitted` reads `self.outbox`
        # unconditionally, RFC-0003 §Execution Model) is unchanged by this RFC.
        self.assertEqual(len(interp.outbox), 1)
        # The durable store is what must not leak the failed run's emission.
        self.assertEqual(repository.drain_outbox(), [])

    def test_a_completing_run_keeps_its_outbox_row(self):
        """정상: 실행이 끝까지 성공하면 emission이 durable하게 남는다."""
        repository = self._repository("sqlite")
        payload = {"id": "o-2"}

        result, _ = self.execute(EMIT_ONLY, payload, "sqlite", seed=False,
                                 repository=repository)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(repository.drain_outbox()), 1)


if __name__ == "__main__":
    unittest.main()
