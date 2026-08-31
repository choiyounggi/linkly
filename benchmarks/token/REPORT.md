# REPORT — 토큰 절약 실측 (issue #142)

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

## 소스 토큰 표

동등성 정의: [equiv/MAPPING.md](equiv/MAPPING.md) — 엔티티 필드, 엔드포인트, URL
refinement, cache TTL, retry policy 1:1 대응 + 이식 spec 3케이스
(`tests/test_equiv_spec.py`, 정상/에러/경계).

| 파일 | 문자 수 | 공백 제외 문자 수 | 토큰(o200k_base) | 토큰(cl100k_base) |
|---|---:|---:|---:|---:|
| `examples/linkhub.lnpl` | 2617 | 1770 | **893** | **1088** |
| `benchmarks/token/equiv/linkhub_fastapi.py` | 5625 | 4348 | **1353** | **1337** |

이 예제(LinkHub — 엔티티 1개, 워크플로 2개, spec 3블록)에서 LNPL 소스는
FastAPI 등가 구현보다 o200k_base 기준 약 34%, cl100k_base 기준 약 19% 적은
토큰이다. 단일 예제 수치이며 일반화 주장이 아니다(한계 각주 1 참조).

## 편집 토큰 표

두 수정 태스크를 같은 베이스라인(examples/linkhub.lnpl / equiv/linkhub_fastapi.py)에
독립적으로 적용. 편집 토큰 = `difflib.unified_diff`가 낸 `+`/`-` 콘텐츠 라인의
토큰 합(마커 문자 `+`/`-` 자체는 제외).

| 수정 태스크 | 구현 | 추가 줄 | 삭제 줄 | 편집 토큰(o200k_base) | 편집 토큰(cl100k_base) |
|---|---|---:|---:|---:|---:|
| M1 — `note` 필드 추가 | `.lnpl` | 1 | 0 | **3** | **3** |
| M1 — `note` 필드 추가 | FastAPI | 5 | 0 | **32** | **32** |
| M2 — URL 중복 거부 가드 | `.lnpl` | 28 | 3 | **492** | **631** |
| M2 — URL 중복 거부 가드 | FastAPI | 18 | 0 | **226** | **227** |

M1은 LNPL이 FastAPI보다 훨씬 저렴하다(필드 선언 한 줄 대 dataclass/pydantic
모델 두 곳 + 응답 두 곳, 4곳 수정). **M2는 반대다 — LNPL이 FastAPI보다 비싸고,
그마저도 기능이 틀렸다.** 한계 각주 2·3에 그대로 적는다.

## 한계 각주 (불리해도 그대로 — qa/REPORT.md 각주 선례를 따름)

1. **단일 예제.** 측정 대상은 examples/linkhub.lnpl 하나(엔티티 1개, 워크플로
   2개)뿐이다. 소스/편집 토큰 비율이 다른 도메인·규모의 `.lnpl`에 일반화된다는
   근거는 이 리포트에 없다.
2. **M2는 LNPL 0.6.0 어휘로 표현 불가능하다는 것을 실측으로 확인했다.**
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
3. **M2의 LNPL 편집 토큰(492/631)은 실패를 설명하는 주석이 대부분을
   차지한다.** 순수 기능 diff(`find bookmark` 한 줄 + 실패를 계약하는 spec
   블록들)만 떼면 훨씬 적지만, `measure_tokens.py`는 커밋된 diff 그대로
   센다(주석 제거 후처리는 범위 밖 — PROTOCOL.md "편집 토큰 측정" 참조).
   즉 이 수치를 "LNPL에서 이 가드를 추가하는 비용"으로 곧이곧대로 읽으면 안
   된다 — 애초에 요청한 기능이 만들어지지 않았다는 사실이 먼저다(각주 2).
4. **정확도(accuracy)는 측정하지 않았다.** "동등하다"는 주장은
   equiv/MAPPING.md의 필드/엔드포인트 대응표와 이식 spec 3케이스(정상/에러/
   경계) 통과로만 뒷받침된다 — 전수 행위 동등성 검증이 아니다. LNPL의 `spec`
   `effects complete` 키(no-op 스텝 없음)는 FastAPI 쪽에 대응하는 개념이
   없어 이식하지 않았다(PROTOCOL.md).
5. **pass@k는 하네스만이다.** `passk/harness.py` + 스텁 생성기 단위 테스트
   (n=k, c=0, c=n 경계, 에러 케이스 포함, `tests/test_passk_harness.py`)까지만
   범위다. 실제 LLM API 호출로 얻는 pass@k 수치는 이 태스크의 범위 밖(사용자
   결정, PROTOCOL.md "pass@k 하네스" 절).
6. **성능·동시성·장기 운영·실 부하는 측정하지 않았다** —
   docs/scale-pressure-measurement.md·qa/REPORT.md와 같은 미측정 축.

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
    }
  },
  "source_tokens": {
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
      "path": "examples/linkhub.lnpl",
      "tokens_cl100k_base": 1088,
      "tokens_o200k_base": 893
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
