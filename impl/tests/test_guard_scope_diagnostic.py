"""`guard-orphaned-steps` — 가드가 지키려던 상태를 가드 밖에서 만지는 스텝 (RFC-0023).

가드는 **바로 다음 항목 하나**만 소유한다. 문법은 그렇게 정해져 있고
`references/grammar.md`도 그렇게 적어 두었다. 문제는 그 사실이 작성 시점에
아무 데서도 보이지 않는다는 것이었다:

    when product.stock >= input.quantity
    create order
    set product.stock to product.stock - input.quantity

이건 진단 0건으로 컴파일되고, 가드가 거짓인 실행에서도 재고를 깎는다. 유일한
신호였던 `guard-skipped-steps`는 **런타임** 진단이고, 그나마 가드가 실제로
소유한 한 스텝에 대해서만 말한다.

판정은 형태가 아니라 결과다. "가드 뒤에 스텝이 있다"는 정상이고 모든 워크플로가
그렇게 생겼다. 경고할 값어치가 있는 것은 **가드가 지키려던 그 상태를** 가드
밖에서 만지는 스텝이다. 그래서 조건이 참조하는 엔티티가 보호 집합을 정하고,
그 집합을 건드리는 뒤쪽 비가드 스텝만 보고된다.

이 파일이 지키는 두 방향:
  * 실제 함정(must-fail 픽스처)에서 정확히 발화하는가
  * 커밋된 예제 넷과 무관한 후속 스텝(must-pass 픽스처)에서 침묵하는가

둘째가 없으면 이 진단은 예외 목록을 키우다 아무것도 측정하지 않게 된다
(이슈 #35에서 이 레포가 한 번 겪은 실패다).
"""
import glob
import os
import unittest

from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lnpl_fixtures")

CODE = "guard-orphaned-steps"

# 가드가 마지막 항목이라 뒤에 아무것도 없다 — 경계.
GUARD_IS_LAST = """entity Product
    field
        id UUID
        stock Integer

workflow Place
    find product
    when product.stock > 0
    read product
"""

# 조건이 payload만 본다. 보호할 행이 없으므로 발화하지 않는다 — 경계.
PAYLOAD_ONLY_GUARD = """entity Product
    field
        id UUID
        stock Integer

workflow Place
    find product
    when input.stock > 0
    read product
    update product
"""

# 가드가 지키는 **바로 그 엔티티**를 가드 밖에서 `cache`한다. RFC-0023 §4는
# CacheAccess가 보호 집합에 기여하지 **않는다**고 정했다 — 이 진단이 말하는 것은
# 저장된 상태의 변경이고 캐시 쓰기는 그 범주가 아니기 때문이다. 그 결정을
# 반증 가능하게 만드는 것이 이 입력의 유일한 목적이다: CacheAccess가 기여하게
# 바뀌면 여기서 즉시 빨개진다.
#
# `guard_orphan_pass.lnpl`은 이 일을 하지 못한다. 거기 `cache order`는 가드가
# 지키는 `entity.product`와 애초에 다른 엔티티라, CacheAccess가 기여하든 말든
# 교집합이 비어 있다.
CACHE_ON_THE_PROTECTED_ENTITY = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

workflow Place
    validate product
    find product
    when product.stock > 0
    create order
    cache product
"""

# `repeat`은 조건이 아니라 횟수를 담는다 — 경계.
REPEAT_GUARD = """entity Product
    field
        id UUID
        stock Integer

workflow Place
    find product
    repeat 2
    read product
    update product
"""

TWO_ORPHANS = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

workflow PlaceOrder
    validate product
    find product
    when product.stock > 0
    create order
    set product.stock to product.stock - 1
    update product
"""

# 진단이 권하는 두 해법. 문면이 참이 아니면 그건 잘못된 안내다.
FIXED_BY_REPEATING_THE_GUARD = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

workflow PlaceOrder
    validate product
    find product
    when product.stock > 0
    create order
    when product.stock > 0
    set product.stock to product.stock - 1
"""

FIXED_BY_A_PARALLEL_BLOCK = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

workflow PlaceOrder
    validate product
    find product
    when product.stock > 0
    parallel
    create order
    set product.stock to product.stock - 1
    merge
"""


def diagnose(source, name="probe"):
    """`source`가 내는 이 코드의 진단들 — 컴파일러가 판정한다."""
    module = lower(parse(source), name)
    return list(module.diagnostics.by_code(CODE))


def read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class TheCodeIsRegistered(unittest.TestCase):

    def test_the_code_exists(self):
        self.assertIn(CODE, CODES)

    def test_it_is_a_warning(self):
        # RFC-0021: warning은 프로그램을 고치면 사라지는 것, info는 고쳐도
        # 사라지지 않는 플랫폼 상태의 진술. 이건 고치면 사라진다.
        self.assertEqual(SEVERITY_OF[CODE], "warning")


class TheControlPair(unittest.TestCase):
    """커밋된 통제쌍. 골든에 이 형태가 없어서 골든 변형으로는 검증되지 않는다."""

    def test_the_fail_fixture_reports_exactly_one(self):
        found = diagnose(read_fixture("guard_orphan_fail.lnpl"))
        self.assertEqual(len(found), 1, [d.subject for d in found])
        self.assertEqual(found[0].subject, "set product.stock to product.stock - 1")

    def test_the_fail_fixture_names_the_orphan_line_and_the_guard(self):
        found = diagnose(read_fixture("guard_orphan_fail.lnpl"))[0]
        # `where`는 저자가 옮겨야 할 스텝의 자리다 — 가드 줄이 아니라.
        self.assertEqual(found.where, "line 16")
        self.assertIn("when product.stock > 0", found.message)
        self.assertIn("parallel", found.message)

    def test_the_pass_fixture_reports_nothing(self):
        self.assertEqual(diagnose(read_fixture("guard_orphan_pass.lnpl")), [])

    def test_the_pass_fixture_is_otherwise_clean(self):
        # 통제가 통제이려면 다른 진단이 섞여 있으면 안 된다.
        module = lower(parse(read_fixture("guard_orphan_pass.lnpl")), "pass")
        self.assertEqual(list(module.diagnostics.all()), [])


class EveryOrphanIsNamed(unittest.TestCase):

    def test_two_orphans_produce_two_diagnostics(self):
        found = diagnose(TWO_ORPHANS)
        self.assertEqual([d.where for d in found], ["line 16", "line 17"])


class TheRemediesItRecommendsActuallyWork(unittest.TestCase):
    """권하는 고침이 실제로 진단을 없애지 못하면 그 문면은 거짓이다."""

    def test_repeating_the_guard_line_silences_it(self):
        self.assertEqual(diagnose(FIXED_BY_REPEATING_THE_GUARD), [])

    def test_wrapping_both_in_parallel_silences_it(self):
        self.assertEqual(diagnose(FIXED_BY_A_PARALLEL_BLOCK), [])


class ItStaysQuietWhereThereIsNoConsequence(unittest.TestCase):

    def test_a_guard_with_nothing_after_it(self):
        self.assertEqual(diagnose(GUARD_IS_LAST), [])

    def test_a_condition_that_only_reads_the_payload(self):
        # `input.`은 실행 payload지 이 워크플로가 소유한 행이 아니다.
        self.assertEqual(diagnose(PAYLOAD_ONLY_GUARD), [])

    def test_a_repeat_guard_carries_a_count_not_a_condition(self):
        self.assertEqual(diagnose(REPEAT_GUARD), [])

    def test_a_cache_write_on_the_protected_entity_is_not_a_state_change(self):
        # RFC-0023 §4의 결정을 반증 가능하게 붙든다. `_touched_entities`가
        # CacheAccess를 기여하게 바뀌면 이 단언이 깨진다.
        self.assertEqual(diagnose(CACHE_ON_THE_PROTECTED_ENTITY), [])


class TwoGuardsOverTheSameEntity(unittest.TestCase):
    """가드 아래 있는 것은 이미 조건부다 — 그게 **다른** 가드여도 그렇다.

    이 클래스가 `_steps_outside_guards`의 Guard 건너뛰기를 붙드는 유일한
    자리다. `examples/guarded.lnpl`은 이 일을 하지 못한다: 그 파일의 두 번째
    가드 스텝은 `call`이고 `NetworkCall`은 보호 집합에 기여하는 Effect가
    아니어서, 건너뛰기를 없애도 조용하다. 여기서는 두 가드가 **같은 엔티티**를
    두고 서 있으므로 건너뛰기가 실제로 판정에 개입한다.
    """

    def test_the_second_guard_shields_its_own_step(self):
        self.assertEqual(diagnose(FIXED_BY_REPEATING_THE_GUARD), [])


class ShippedExamplesStaySilent(unittest.TestCase):
    """예제를 고쳐야 통과한다면 발화 조건이 틀린 것이다."""

    def test_no_shipped_example_reports_this(self):
        paths = sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl")))
        self.assertGreaterEqual(len(paths), 4, "예제를 하나도 못 찾으면 공허하다")
        for path in paths:
            with self.subTest(example=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                found = diagnose(source, os.path.basename(path))
                self.assertEqual(
                    found, [],
                    "%s 가 %s 를 낸다. 예제가 아니라 발화 조건을 좁혀라."
                    % (os.path.basename(path), CODE))


if __name__ == "__main__":
    unittest.main()
