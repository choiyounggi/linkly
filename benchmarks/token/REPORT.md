# REPORT — 토큰 절약 실측 (issue #142, #251)

방법은 [PROTOCOL.md](PROTOCOL.md), 동등성 정의는 [equiv/MAPPING.md](equiv/MAPPING.md)에
있다. 이 문서는 그 방법으로 나온 **수치**와 **한계**만 담는다 — 결론(플랫폼
주장이 이 예제에서 성립하는지)은 이 문서가 내리지 않는다.

재현:

```bash
benchmarks/token/.venv/bin/python benchmarks/token/measure_tokens.py
```

## 토크나이저

| 항목 | 값 |
|---|---|
| 라이브러리 | `tiktoken` |
| 버전 | `0.14.0` |
| 인코딩 1 | `o200k_base` (gpt-4o, gpt-4o-mini) |
| 인코딩 2 | `cl100k_base` (gpt-4, gpt-3.5-turbo) |

출처: PROTOCOL.md "토크나이저 선택" 절 (openai/tiktoken, openai-cookbook 인코딩 표).

## 시나리오

| 시나리오 | LNPL | FastAPI | 다루는 것 | MAPPING |
|---|---|---|---|---|
| checkout | `examples/checkout.lnpl` | `equiv/checkout_fastapi.py` | validate, guard, retry, timeout, cache, jwt, SLO | `checkout` |
| consume | `scenarios/consume.lnpl` | `equiv/consume_fastapi.py` | `consume by` + CloudEvents 라우트 | `consume` |
| schedule | `scenarios/schedule.lnpl` | `equiv/schedule_fastapi.py` | `on schedule` + 트리거 라우트, list/count/update | `schedule` |
| parallel | `scenarios/parallel.lnpl` | `equiv/parallel_fastapi.py` | `parallel 2` 팬아웃 | `parallel` |
| cached | `scenarios/cached.lnpl` | `equiv/cached_fastapi.py` | `find ... cached` read-through | `cached` |
| linkhub | `scenarios/linkhub.lnpl` | `equiv/linkhub_fastapi.py` | issue #142 쌍, 43d8bbd 시점으로 고정 | `linkhub` |

## 소스 토큰 표

동등성 정의: [equiv/MAPPING.md](equiv/MAPPING.md) (시나리오별 절).

| 시나리오 | 파일 | 문자 수 | 공백 제외 문자 수 | 토큰(o200k_base) | 토큰(cl100k_base) |
|---|---|---:|---:|---:|---:|
| `checkout` | `examples/checkout.lnpl` | 1461 | 958 | **418** | **471** |
| `checkout` | `benchmarks/token/equiv/checkout_fastapi.py` | 4918 | 3874 | **1210** | **1210** |
| `consume` | `benchmarks/token/scenarios/consume.lnpl` | 826 | 496 | **172** | **177** |
| `consume` | `benchmarks/token/equiv/consume_fastapi.py` | 5419 | 4277 | **1351** | **1351** |
| `schedule` | `benchmarks/token/scenarios/schedule.lnpl` | 811 | 497 | **173** | **172** |
| `schedule` | `benchmarks/token/equiv/schedule_fastapi.py` | 2370 | 1827 | **562** | **563** |
| `parallel` | `benchmarks/token/scenarios/parallel.lnpl` | 863 | 500 | **183** | **181** |
| `parallel` | `benchmarks/token/equiv/parallel_fastapi.py` | 3018 | 2398 | **705** | **702** |
| `cached` | `benchmarks/token/scenarios/cached.lnpl` | 729 | 436 | **148** | **144** |
| `cached` | `benchmarks/token/equiv/cached_fastapi.py` | 2965 | 2372 | **750** | **751** |
| `linkhub` | `benchmarks/token/scenarios/linkhub.lnpl` | 2617 | 1770 | **893** | **1088** |
| `linkhub` | `benchmarks/token/equiv/linkhub_fastapi.py` | 5625 | 4348 | **1353** | **1337** |

## 편집 종류

| 편집 종류 | 베이스라인 | `.lnpl` 변경 | FastAPI 변경 |
|---|---|---|---|
| `m1_note_field` | linkhub | `note` 필드 한 줄 | dataclass·pydantic 모델 + 응답 두 곳 |
| `m2_duplicate_guard` | linkhub | URL 중복 거부 가드 시도 (한계 각주 8) | `url_index` + 409 분기 |
| `m3_add_workflow` | cached | `workflow SaveProduct` | `save_product` + 라우트 |
| `m4_cached_read` | consume | `find order cached` + `performance cache 5m` | read-through + TTL |
| `m5_timeout_policy` | schedule | `timeout 2s` | 데드라인 + 504 |

각 편집은 베이스라인 시나리오에 독립적으로 적용한다. 편집 토큰 =
`difflib.unified_diff`가 낸 `+`/`-` 콘텐츠 라인의 토큰 합(마커 문자 `+`/`-`
자체는 제외).

## 편집 토큰 표

| 편집 종류 | 구현 | 추가 줄 | 삭제 줄 | 편집 토큰(o200k_base) | 편집 토큰(cl100k_base) |
|---|---|---:|---:|---:|---:|
| `m1_note_field` | `lnpl` | 1 | 0 | **3** | **3** |
| `m1_note_field` | `fastapi` | 5 | 0 | **32** | **32** |
| `m2_duplicate_guard` | `lnpl` | 28 | 3 | **492** | **631** |
| `m2_duplicate_guard` | `fastapi` | 18 | 0 | **226** | **227** |
| `m3_add_workflow` | `lnpl` | 13 | 0 | **45** | **45** |
| `m3_add_workflow` | `fastapi` | 20 | 0 | **156** | **156** |
| `m4_cached_read` | `lnpl` | 3 | 1 | **16** | **16** |
| `m4_cached_read` | `fastapi` | 14 | 1 | **148** | **148** |
| `m5_timeout_policy` | `lnpl` | 1 | 0 | **5** | **5** |
| `m5_timeout_policy` | `fastapi` | 15 | 2 | **155** | **154** |

## 한계 각주 (불리해도 그대로 — qa/REPORT.md 각주 선례를 따름)

1. **규모.** 측정 대상은 시나리오 여섯 개이며, 각각 엔티티 1~2개와 워크플로
   1~3개뿐이다. 이 범위 밖의 `.lnpl`에 대한 주장은 이 리포트에 없다.
2. **저장소.** 두 쪽 모두 인메모리다. issue #251의 "FastAPI+SQLAlchemy"는
   FastAPI + 인메모리 Store로 측정했다(코디네이터 결정) — LNPL 쪽이
   `interp.FakeRepository` 위에서 돌기 때문이다. ORM 계층을 붙이면 여기서
   세지 않은 Python 토큰이 더해진다.
3. **표면.** FastAPI 쪽은 LNPL 런타임이 소스에서 파생하는 것(파생 GET 라우트,
   CloudEvents 봉투 검사, 상태 코드)을 손으로 쓴다. 어느 쪽도 세지 않는
   표면은 MAPPING에 적었다.
4. **주석.** 새 쌍은 양쪽 모두 2줄 헤더만 둔다. checkout과 linkhub는 주석까지
   포함한 원본 그대로 측정했다.
5. **checkout 드리프트.** `examples/checkout.lnpl`은 고정 사본이 아니라 현재
   파일을 측정한다. 이 파일을 고치면 REPORT를 재생성하고 포트를 다시 확인할
   때까지 `tests/test_report_block.py`가 빨갛게 된다.
6. **linkhub 행.** RFC-0048이 `CountPopularBookmarks`를 더하기 전인 43d8bbd
   시점의 고정 사본이다. 포트는 issue #142의 모양(REST 경로, 201/422, 재시도
   3회 대 LNPL 4회)을 유지한다.
7. **검증.** 포트는 인터프리터의 필드 검사를 손으로 다시 구현한다. pydantic의
   규칙은 다르다(MAPPING Conventions 참조).
8. **M2는 LNPL 0.6.0 어휘로 표현 불가능하다는 것을 실측으로 확인했다.**
   `SaveBookmark`에 "URL 중복 거부, 신규는 허용"을 걸려면 가드가 필요하지만,
   가드 조건은 Integer/DateTime 필드만 참조할 수 있고(url은 Text refinement),
   행 존재 여부를 실패 없이 미리 검사하는 구문도 없다(`find`는 미발견 시
   RunError). 표현 가능한 가장 가까운 방어(`find`로 먼저 읽어 `create`가
   (entity, id) 키로 충돌하게 함)를 달아 `lnpl spec --run`으로 직접 실행해
   확인한 결과: **이 워크플로는 어떤 입력에도 성공하지 않는다** — 새 id는
   `find`에서, 이미 있는 id는 `create` 충돌에서 각각 실패한다
   (`edits/m2_duplicate_guard/lnpl_after.lnpl`, 12/12 spec 통과 — "항상
   실패"를 spec 자신이 계약한다). FastAPI 쪽은 `url_index` 딕셔너리로 신규
   201 / 중복 409 / 다른 신규 URL 201을 실제로 검증했다
   (`edits/m2_duplicate_guard/fastapi_after.py`). 이 비대칭은 "LNPL이 토큰을
   아낀다"는 플랫폼 주장에 정면으로 불리한 발견이며, 그대로 남긴다.

   **M2의 LNPL 편집 토큰(492/631)은 실패를 설명하는 주석이 대부분을
   차지한다.** 순수 기능 diff(`find bookmark` 한 줄 + 실패를 계약하는 spec
   블록들)만 떼면 훨씬 적지만, `measure_tokens.py`는 커밋된 diff 그대로
   센다(주석 제거 후처리는 범위 밖 — PROTOCOL.md "편집 토큰 측정" 참조).
   즉 이 수치를 "LNPL에서 이 가드를 추가하는 비용"으로 곧이곧대로 읽으면 안
   된다 — 애초에 요청한 기능이 만들어지지 않았다는 사실이 먼저다(이 각주의
   첫 문단).
9. **동등성 근거.** MAPPING 행 + 이식한 spec 블록 + forcing-input 테스트가
   전부다. 두 쪽은 그 입력에서만 일치함이 확인됐다. 테스트하지 않은 축
   (데드라인, 캐시 TTL 만료, 재시도 횟수, 이벤트 재전달, 64비트를 넘는 정수)은
   MAPPING에 적었다. LNPL의 `spec` `effects complete` 키는 FastAPI 쪽에 대응이
   없어 이식하지 않았다.
10. **pass@k는 범위 밖이다** (#251 Phase 0 사용자 결정). `passk/harness.py`는
    하네스만이다. 실제 pass@k 수치는 후속 이슈다.
11. **토크나이저.** OpenAI 인코딩 두 개만 쓴다.
12. **성능·동시성(부하 하)·장기 운영은 측정하지 않았다** —
    docs/scale-pressure-measurement.md·qa/REPORT.md와 같은 미측정 축.
13. **CI.** 벤치마크 테스트는 벤치마크 venv에서만 돌고 CI에서는 돌지 않는다
    (후속 과제).

## 원본 산출 (손 편집 금지 구획 — measure_tokens.py 출력 그대로)

<!-- BEGIN measure_tokens.py output — do not hand-edit; regenerate with:
     benchmarks/token/.venv/bin/python benchmarks/token/measure_tokens.py -->

```json
{
  "edit_tokens": {
    "m1_note_field": {
      "fastapi": {
        "added_lines": 5,
        "added_tokens_cl100k_base": 32,
        "added_tokens_o200k_base": 32,
        "after_path": "benchmarks/token/edits/m1_note_field/fastapi_after.py",
        "before_path": "benchmarks/token/edits/m1_note_field/fastapi_before.py",
        "edit_tokens_cl100k_base": 32,
        "edit_tokens_o200k_base": 32,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      },
      "lnpl": {
        "added_lines": 1,
        "added_tokens_cl100k_base": 3,
        "added_tokens_o200k_base": 3,
        "after_path": "benchmarks/token/edits/m1_note_field/lnpl_after.lnpl",
        "before_path": "benchmarks/token/edits/m1_note_field/lnpl_before.lnpl",
        "edit_tokens_cl100k_base": 3,
        "edit_tokens_o200k_base": 3,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      }
    },
    "m2_duplicate_guard": {
      "fastapi": {
        "added_lines": 18,
        "added_tokens_cl100k_base": 227,
        "added_tokens_o200k_base": 226,
        "after_path": "benchmarks/token/edits/m2_duplicate_guard/fastapi_after.py",
        "before_path": "benchmarks/token/edits/m2_duplicate_guard/fastapi_before.py",
        "edit_tokens_cl100k_base": 227,
        "edit_tokens_o200k_base": 226,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      },
      "lnpl": {
        "added_lines": 28,
        "added_tokens_cl100k_base": 619,
        "added_tokens_o200k_base": 480,
        "after_path": "benchmarks/token/edits/m2_duplicate_guard/lnpl_after.lnpl",
        "before_path": "benchmarks/token/edits/m2_duplicate_guard/lnpl_before.lnpl",
        "edit_tokens_cl100k_base": 631,
        "edit_tokens_o200k_base": 492,
        "removed_lines": 3,
        "removed_tokens_cl100k_base": 12,
        "removed_tokens_o200k_base": 12
      }
    },
    "m3_add_workflow": {
      "fastapi": {
        "added_lines": 20,
        "added_tokens_cl100k_base": 156,
        "added_tokens_o200k_base": 156,
        "after_path": "benchmarks/token/edits/m3_add_workflow/fastapi_after.py",
        "before_path": "benchmarks/token/edits/m3_add_workflow/fastapi_before.py",
        "edit_tokens_cl100k_base": 156,
        "edit_tokens_o200k_base": 156,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      },
      "lnpl": {
        "added_lines": 13,
        "added_tokens_cl100k_base": 45,
        "added_tokens_o200k_base": 45,
        "after_path": "benchmarks/token/edits/m3_add_workflow/lnpl_after.lnpl",
        "before_path": "benchmarks/token/edits/m3_add_workflow/lnpl_before.lnpl",
        "edit_tokens_cl100k_base": 45,
        "edit_tokens_o200k_base": 45,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      }
    },
    "m4_cached_read": {
      "fastapi": {
        "added_lines": 14,
        "added_tokens_cl100k_base": 130,
        "added_tokens_o200k_base": 130,
        "after_path": "benchmarks/token/edits/m4_cached_read/fastapi_after.py",
        "before_path": "benchmarks/token/edits/m4_cached_read/fastapi_before.py",
        "edit_tokens_cl100k_base": 148,
        "edit_tokens_o200k_base": 148,
        "removed_lines": 1,
        "removed_tokens_cl100k_base": 18,
        "removed_tokens_o200k_base": 18
      },
      "lnpl": {
        "added_lines": 3,
        "added_tokens_cl100k_base": 13,
        "added_tokens_o200k_base": 13,
        "after_path": "benchmarks/token/edits/m4_cached_read/lnpl_after.lnpl",
        "before_path": "benchmarks/token/edits/m4_cached_read/lnpl_before.lnpl",
        "edit_tokens_cl100k_base": 16,
        "edit_tokens_o200k_base": 16,
        "removed_lines": 1,
        "removed_tokens_cl100k_base": 3,
        "removed_tokens_o200k_base": 3
      }
    },
    "m5_timeout_policy": {
      "fastapi": {
        "added_lines": 15,
        "added_tokens_cl100k_base": 128,
        "added_tokens_o200k_base": 129,
        "after_path": "benchmarks/token/edits/m5_timeout_policy/fastapi_after.py",
        "before_path": "benchmarks/token/edits/m5_timeout_policy/fastapi_before.py",
        "edit_tokens_cl100k_base": 154,
        "edit_tokens_o200k_base": 155,
        "removed_lines": 2,
        "removed_tokens_cl100k_base": 26,
        "removed_tokens_o200k_base": 26
      },
      "lnpl": {
        "added_lines": 1,
        "added_tokens_cl100k_base": 5,
        "added_tokens_o200k_base": 5,
        "after_path": "benchmarks/token/edits/m5_timeout_policy/lnpl_after.lnpl",
        "before_path": "benchmarks/token/edits/m5_timeout_policy/lnpl_before.lnpl",
        "edit_tokens_cl100k_base": 5,
        "edit_tokens_o200k_base": 5,
        "removed_lines": 0,
        "removed_tokens_cl100k_base": 0,
        "removed_tokens_o200k_base": 0
      }
    }
  },
  "source_tokens": {
    "cached": {
      "fastapi": {
        "chars": 2965,
        "chars_no_whitespace": 2372,
        "path": "benchmarks/token/equiv/cached_fastapi.py",
        "tokens_cl100k_base": 751,
        "tokens_o200k_base": 750
      },
      "lnpl": {
        "chars": 729,
        "chars_no_whitespace": 436,
        "path": "benchmarks/token/scenarios/cached.lnpl",
        "tokens_cl100k_base": 144,
        "tokens_o200k_base": 148
      }
    },
    "checkout": {
      "fastapi": {
        "chars": 4918,
        "chars_no_whitespace": 3874,
        "path": "benchmarks/token/equiv/checkout_fastapi.py",
        "tokens_cl100k_base": 1210,
        "tokens_o200k_base": 1210
      },
      "lnpl": {
        "chars": 1461,
        "chars_no_whitespace": 958,
        "path": "examples/checkout.lnpl",
        "tokens_cl100k_base": 471,
        "tokens_o200k_base": 418
      }
    },
    "consume": {
      "fastapi": {
        "chars": 5419,
        "chars_no_whitespace": 4277,
        "path": "benchmarks/token/equiv/consume_fastapi.py",
        "tokens_cl100k_base": 1351,
        "tokens_o200k_base": 1351
      },
      "lnpl": {
        "chars": 826,
        "chars_no_whitespace": 496,
        "path": "benchmarks/token/scenarios/consume.lnpl",
        "tokens_cl100k_base": 177,
        "tokens_o200k_base": 172
      }
    },
    "linkhub": {
      "fastapi": {
        "chars": 5625,
        "chars_no_whitespace": 4348,
        "path": "benchmarks/token/equiv/linkhub_fastapi.py",
        "tokens_cl100k_base": 1337,
        "tokens_o200k_base": 1353
      },
      "lnpl": {
        "chars": 2617,
        "chars_no_whitespace": 1770,
        "path": "benchmarks/token/scenarios/linkhub.lnpl",
        "tokens_cl100k_base": 1088,
        "tokens_o200k_base": 893
      }
    },
    "parallel": {
      "fastapi": {
        "chars": 3018,
        "chars_no_whitespace": 2398,
        "path": "benchmarks/token/equiv/parallel_fastapi.py",
        "tokens_cl100k_base": 702,
        "tokens_o200k_base": 705
      },
      "lnpl": {
        "chars": 863,
        "chars_no_whitespace": 500,
        "path": "benchmarks/token/scenarios/parallel.lnpl",
        "tokens_cl100k_base": 181,
        "tokens_o200k_base": 183
      }
    },
    "schedule": {
      "fastapi": {
        "chars": 2370,
        "chars_no_whitespace": 1827,
        "path": "benchmarks/token/equiv/schedule_fastapi.py",
        "tokens_cl100k_base": 563,
        "tokens_o200k_base": 562
      },
      "lnpl": {
        "chars": 811,
        "chars_no_whitespace": 497,
        "path": "benchmarks/token/scenarios/schedule.lnpl",
        "tokens_cl100k_base": 172,
        "tokens_o200k_base": 173
      }
    }
  },
  "tiktoken_version": "0.14.0",
  "tokenizers": [
    "o200k_base",
    "cl100k_base"
  ]
}
```

<!-- END measure_tokens.py output -->
