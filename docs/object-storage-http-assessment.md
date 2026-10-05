# `capability http`로 오브젝트 스토리지가 가능한가 (issue #193)

issue #193의 1단계 판정 문서다. `.lnpl`에는 오브젝트 스토리지(S3/GCS/Blob) 전용
capability가 없다. 유일한 우회는 `capability http`로 스토리지 API를 직접 부르는
것뿐이다. 이 문서는 세 시나리오(업로드 저장, 서명 URL 발급, 대용량 다운로드)를
실제로 써 보고, 그 우회가 어디까지 가는지, 어디서 부족한지를 실행 결과로
기록한다. **이 문서가 내리는 결정은 하나**: "http 우회로 충분하다(close)" 또는
"RFC를 열어야 한다(open)"이며, 연다면 최소 연산 집합을 함께 적는다. IR·문법·SPI
설계는 이 문서의 범위 밖이다 — 그 판단이 "열자"로 나온 경우에만, 이후 별도
작업에서 RFC로 진행한다.

## 환경

- commit: cc3ace1 (브리프가 가리키는 통합 브랜치 `orch/open-issues-1002`의 tip)
- python: 3.13 (`.venv/bin/python`, 워크트리 로컬 venv)
- 서버: 전부 로컬 mock — `http.server.ThreadingHTTPServer`를 루프백
  (`127.0.0.1`)의 임시 포트에 띄운다. 도커도 실제 네트워크도 쓰지 않는다
  (`impl/tests/test_network_driver.py`의 `_ServerTestCase`와 같은 방식).
- 실행: `PYTHONPATH=impl .venv/bin/python -m lnpl <subcommand>` 또는 설치된
  `lnpl` 콘솔 스크립트(`pyproject.toml`의 `lnpl = "lnpl.cli:main"`). **주의**:
  `python -m lnpl.cli`는 조용히 아무것도 출력하지 않는다 — `lnpl.cli`는
  라이브러리 모듈이고 `if __name__ == "__main__":` 가드는 `impl/lnpl/__main__.py`
  에만 있다. 아래 모든 명령은 `python -m lnpl` 또는 `lnpl` 콘솔 스크립트로
  실행한 것이며, 재현할 때도 반드시 그렇게 해야 한다.
- 모든 예시의 버킷·키·서명값은 가짜다(`example-bucket`, `FAKESIGNATURE0000` 등).
  실제 서비스에서 온 값은 어디에도 없다.

## `capability http`가 오늘 제공하는 것 (file:line, cc3ace1에서 재검증)

| 항목 | 내용 | 근거 |
|------|------|------|
| 요청 본문 | 워크플로 입력 페이로드 전체가 JSON으로 직렬화되어 본문이 된다. GET에는 본문이 없다. Content-Type은 `application/json`으로 강제된다 | `impl/lnpl/drivers.py:1608-1610`; `impl/lnpl/interp.py:2195`(`self.network.call(effect["target"], payload, ...)` — `payload`는 워크플로 입력 전체) |
| 인증 | capability당 정적 헤더 하나뿐: `auth bearer from <ENV>` 또는 `auth apikey <HEADER> from <ENV>`. 요청별·계산된 헤더는 없다 | `impl/lnpl/lower.py:208`(`HTTP_AUTH_KINDS`), `impl/lnpl/lower.py:485-506`(`_parse_http_auth`) |
| 닫힌 절 집합 | `method`/`auth`/`retry`/`breaker`/`path` 다섯 개뿐 — 이 밖의 키워드는 컴파일 에러(`LowerError`)다. 메서드는 `get`/`post`/`put`/`patch`/`delete` | `impl/lnpl/lower.py:207`(`HTTP_METHODS`), `impl/lnpl/lower.py:599-672`(`_parse_http_capability`, 미지원 절은 653-654에서 거부) |
| URL 구성 | `--endpoint`/`LNPL_ENDPOINT_*`로 매핑된 URL + `path` 템플릿의 위치 인자 `{}`. 각 인자는 `safe=""`로 percent-encode된다(키의 `/`도 인코딩됨) | `impl/lnpl/cli.py:1212`(`_open_endpoints`); `impl/lnpl/drivers.py:1557`(`HttpNetworkDriver._resolve`); `impl/lnpl/drivers.py:1413-1422`(`_assemble_path`) |
| 응답 처리 | 응답 본문을 전부 메모리로 읽는다. JSON이 아니거나 JSON이지만 object가 아니면 `{}`로 취급한다. 응답 헤더는 드라이버가 받긴 하지만 인터프리터가 버린다 | `impl/lnpl/drivers.py:1642-1663`(`_send_and_read`); `impl/lnpl/interp.py:2195`(응답 헤더를 `_headers`로 받고 다시 읽지 않음) |
| 바인딩 결과 | `status` + 응답 본문의 최상위 키만 바인딩된다 | `impl/lnpl/interp.py:2220-2222` |
| 서명 | 요청 서명(HMAC 등) 기능이 전혀 없다. `hmac`/`_sign`은 JWT 토큰 공급자 안에만 존재한다 | `impl/lnpl/drivers.py:1106`(`HmacTokenProvider`), `impl/lnpl/drivers.py:1226-1227`(`_sign`) |

브리프가 처음 인용한 file:line 중 두 곳은 어긋나 있었다(위 표는
수정된 값이다): "URL 구성"의 원래 인용은 `drivers.py` 1367-1377/1553-1554였으나
`_open_endpoints`는 `drivers.py`가 아니라 `cli.py`에 있고, driver 쪽 resolve는
1557(1553-1554 아님)이다. "응답 처리"의 원래 인용(`drivers.py` 1607-1620)은
요청 본문을 만드는 코드 구간이고, 실제 응답 읽기/파싱은 1642-1663에 있다.

## 시나리오 1 — 업로드 저장

워크플로:

```lnpl
capability http Storage
    method put
    path "/objects/{}"
entity Upload
    field
        id UUID
        objectKey Text
        content Text
service StorageSvc
workflow StoreUpload
    call Storage with objectKey as p
```

재현: `python -m lnpl compile --strict=warning StoreUpload.lnpl` → rc=0,
stderr 없음(cc3ace1에서 재실행 확인). 실행은
`PYTHONPATH=impl .venv/bin/python -m unittest
tests.test_object_storage_http_assessment.ObjectStorageHttpAssessmentTest.test_json_put_body_reaches_the_mock_server_with_json_content_type -v`

입력(`--payload`): `{"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "objectKey":
"report.pdf", "content": "hello world"}`

mock 서버가 받은 요청(실행 결과):
- method: `PUT`
- path: `/objects/report.pdf`
- header `Content-Type`: `application/json`
- body: `{"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "objectKey": "report.pdf", "content": "hello world"}`

**판정 — 되는 것**: JSON 본문의 PUT/POST는 그대로 된다. 워크플로 입력 페이로드
전부가 그대로 요청 본문이 된다(엔티티 필드와 무관하게).

**판정 — 안 되는 것**: 바이너리 본문, multipart, JSON이 아닌 Content-Type은
표현할 수 없다 — 닫힌 절 집합(`method`/`auth`/`retry`/`breaker`/`path`)에
Content-Type을 바꿀 방법이 없고, 본문은 항상 `json.dumps(payload)`로 고정된다
(`impl/lnpl/drivers.py:1608-1610`). 이 "안 됨"은 추측이 아니라 가장 가까운
표현을 실제로 시도해 확인한 것이다: 그럴듯해 보이는 `upload` 동사를 써 보면

<!-- lnpl-check: skip — 의도적으로 VERB_LEXICON 밖의 동사를 써서 no-op 함정을 보여주는 예시. `--strict=warning`(check_doc_snippets.py가 쓰는 바로 그 플래그)에서는 rc=2로 실패한다 -->
```lnpl
capability http Storage
    method put
entity Upload
    field
        id UUID
        objectKey Text
service StorageSvc
workflow StoreUpload
    upload Storage as p
```

`python -m lnpl compile`은 rc=0이지만 stderr에 정확히 다음을 찍는다:

```
warning: unknown-verb [line 9] (line 9) upload — `upload Storage as p` is outside VERB_LEXICON: this step derives no Effect and runs as a descriptive no-op — did you mean 'load'?
0 info, 1 warning(s), 0 error(s)
```

그리고 컴파일된 LIR에는 `NetworkCall` Effect가 **하나도 없다**(그럴듯해
보이는 동사가 조용한 no-op이 되는 사례, `AGENTS.md`가 "이 플랫폼의 가장 흔한
실패 모드"라고 부르는 것). `--strict=warning`(문서 게이트가 쓰는 바로 그
플래그)로는 rc=2다. 재현:
`PYTHONPATH=impl .venv/bin/python -m unittest
tests.test_object_storage_http_assessment -k test_json_put 2>/dev/null` 대신
위 `upload` 예시를 직접 `python -m lnpl compile --strict=warning`에 넣어보면
된다.

**경계 사례 — 빈 값**: `content` 필드에 빈 문자열 `""`을 넣으면, 그 값은
JSON 본문 안에 `""`로 그대로 왕복한다(워크플로 입력이 통째로 본문이 되므로
"본문이 비어 있다"는 상태 자체가 없다 — GET이 아닌 모든 메서드의 본문은
항상 `json.dumps(payload)`다). 재현:
`ObjectStorageHttpAssessmentTest.test_an_empty_string_field_round_trips_inside_the_always_present_json_body`

**경계 사례 — 키에 `/`가 있을 때**: `objectKey`가 `"uploads/2026/report.pdf"`면
요청 경로는 `/objects/uploads%2F2026%2Freport.pdf`다 — `/`는 `%2F`로
percent-encode되어 하나의 경로 세그먼트로 남는다. 실제 S3류 서비스가 종종
기대하는 "슬래시가 있는 키 = 가상 폴더 구조"는 이 인코딩 때문에 그대로
전달되지 않는다(서버가 `%2F`를 다시 `/`로 풀어주는지는 서버 쪽 구현에
달려 있다 — 이 런타임은 그 디코딩을 하지 않는다). 재현:
`ObjectStorageHttpAssessmentTest.test_an_object_key_containing_a_slash_is_percent_encoded_in_the_path`

**오류 사례**: 스토리지 호출이 500을 돌려주면 `bindings.p == {"error": "disk
full", "status": 500}`로 바인딩된다 — 가드가 `p.status`를 읽어 분기할 수
있다. 접속 자체가 실패하면(연결 거부) `bindings.p == {"status": 0}`로
바인딩된다 — 둘 다 "바인딩된 호출의 전송 실패는 런 실패가 아니라 가드가
읽을 수 있는 값"이라는 RFC-0027 §3 설계대로다. 재현:
`ObjectStorageHttpAssessmentTest.test_a_non_2xx_response_and_a_transport_failure_both_bind_a_branchable_status`

## 시나리오 2 — 서명 URL 발급

### 2a. 다른 서비스가 반환한 서명 URL을 바인딩하기 — 된다

워크플로:

```lnpl
capability http Presign
    method post
entity PresignRequest
    field
        id UUID
        objectKey Text
service PresignSvc
workflow GetPresignedUrl
    call Presign as p
```

mock 서버가 `{"url": "https://example-bucket.s3.example.com/report.pdf?X-Amz-Signature=FAKESIGNATURE0000"}`를
반환하면, `bindings.p.url`이 그 문자열과 정확히 같다. 재현:
`ObjectStorageHttpAssessmentTest.test_a_presigned_url_field_is_bound_from_the_json_response`

**이것이 바로 issue #193 자신이 제안한 "가장 작은 설계"다** — 본문이 런타임을
지나지 않는, presign-only 설계. 서명 URL 발급 서비스를 부르고 그 결과를
바인딩하는 것까지는 이미 된다.

### 2b. 워크플로 스스로 SigV4 같은 서명된 요청을 만들기 — 안 된다

가장 가까운 표현을 시도한다:

<!-- lnpl-check: skip — 의도적으로 닫힌 절 집합 밖의 `sign` 절을 써서 거부를 보여주는 예시. rc=2로 실패한다(재현 참조) -->
```lnpl
capability http Storage
    method put
    sign sigv4
entity Upload
    field
        id UUID
        objectKey Text
service StorageSvc
workflow SignedUpload
    call Storage as p
```

`python -m lnpl compile`은 rc=2, stderr:
``compile error: line 3: capability http takes `method`/`auth`/`retry`/`breaker`/`path`, got 'sign'``.
`capability http`의 닫힌 절 집합(`impl/lnpl/lower.py:599-672`)은
`method`/`auth`/`retry`/`breaker`/`path` 다섯 개뿐이고, 그 밖의 키워드는
조용히 무시되는 게 아니라 **컴파일 에러로 거부**된다 — 2a의 `upload` 동사
사례(조용한 no-op)와는 다른 모양의 실패지만, 같은 하나의 규칙에서 나온다:
이 런타임은 알려지지 않은 입력을 추론하지 않고 닫힌 표(동사 사전 / 절
집합)에서 찾아보고, 없으면 각각의 자리에 맞는 정의된 실패(동사는 no-op
진단, 절은 컴파일 에러)로 답한다. 서명 원시 함수(`hmac`) 자체는 JWT 토큰
공급자 안에만 있고(`impl/lnpl/drivers.py:1106,1226-1227`) `capability http`
경로에는 전혀 연결되어 있지 않다. 재현:
`ObjectStorageHttpAssessmentTest.test_a_sign_clause_is_rejected_at_compile_time`

### 2c. "presign 받고 → 그 URL로 직접 PUT"을 한 워크플로 안에서 체이닝하기 — 안 된다

워크플로:

```lnpl
capability http Presign
    method post
entity PresignRequest
    field
        id UUID
        objectKey Text
service PresignSvc
workflow UploadViaPresignedUrl
    call Presign as p
    call p as q
```

이 블록은 컴파일 자체는 rc=0이라 skip 마커가 필요 없다 — 거부는 컴파일이
아니라 **실행**(`--endpoint` 매핑 부재)에서 난다. `python -m lnpl compile`은
rc=0이고, 컴파일된 LIR에서 두 번째 `NetworkCall`
노드의 `target`은 리터럴 문자열 `"p"`다(`p.url`에 대한 참조가 아니다). `Presign`을
mock 서버에 매핑하고 `p`는 매핑하지 않은 채 실행하면, `python -m lnpl run`은
rc=2, stderr: `error: network target 'p' has no --endpoint mapping or
LNPL_ENDPOINT_P environment variable ...`. **`call`의 target은 언제나
소스에 적힌 컴파일타임 리터럴(capability 이름 또는 URL 리터럴)이며, 이전
스텝이 런타임에 바인딩한 값을 가리킬 수 없다.** 그래서 "서명 URL을 받고 →
그 URL로 실제 PUT까지" 를 워크플로 **하나**가 전부 수행하는 것은 오늘
불가능하다 — 2a가 되는 것은 서명 URL을 받아 바인딩하는 것까지이고, 그
URL로 실제 바이트를 보내는 것은 워크플로 밖의 다른 행위자(클라이언트,
별도 스텝 체인 밖의 프로세스)가 해야 한다. 재현:
`ObjectStorageHttpAssessmentTest.test_a_prior_binding_cannot_be_used_as_a_dynamic_call_target`

## 시나리오 3 — 대용량 다운로드

워크플로:

```lnpl
capability http Storage
    method get
entity DownloadRequest
    field
        id UUID
service StorageSvc
workflow DownloadObject
    call Storage as p
```

mock 서버가 JSON이 아닌 응답(`b"not json at all"`, 16바이트)을 돌려주면
`bindings.p == {"status": 200}`다 — 응답 본문은 버려지고 `status`만 남는다.
같은 서버가 1 MiB(`b"x" * 1048576`) 크기의 역시 JSON이 아닌 응답을
돌려줘도 결과는 완전히 같다(`{"status": 200}`) — 크기와 무관하게 응답
전체를 먼저 메모리로 다 읽은 뒤(`response.read()`,
`impl/lnpl/drivers.py:1642-1663`) JSON 파싱을 시도하고 실패하면 버린다.
즉 **스트리밍이나 크기 제한 없이 응답 전체가 프로세스 메모리에 올라간다** —
"대용량"에 대해 이 런타임이 하는 유일한 일은 "그래도 끝까지 읽는다"이다.
재현: `ObjectStorageHttpAssessmentTest.test_a_non_json_response_binds_as_an_empty_dict_plus_status`

## 테스트하지 않은 것

- 실제 S3/GCS/Azure Blob/MinIO 서버 — 전부 로컬 mock으로만 확인했다(브리프가
  로컬 mock으로 충분하다고 명시한 범위: "무엇을 보내고 바인딩하는가"가
  관심사이지 실서비스 호환성이 아니다)
- 1 MiB보다 훨씬 큰 응답(수백 MB~GB)에서 실제 메모리 사용량이나 타임아웃
  — 읽기 로직이 크기와 무관함은 코드로 확인했으나(§3 인용), 실측은
  1 MiB까지만 했다
- 청크 전송 인코딩(`Transfer-Encoding: chunked`) 요청/응답
- `retry`/`breaker` 절이 스토리지 API의 멱등성 없는 연산(PUT에 재시도)과
  실제로 어떻게 상호작용하는지 — 이 문서가 쓴 캡슐화는 `retry` 절 자체를
  선언하지 않았다
- HTTP/2, 커넥션 재사용이 큰 업로드/다운로드 처리량에 주는 영향

## 재현 명령

```bash
cd <워크트리 루트>
/opt/homebrew/bin/python3.13 -m venv .venv  # 이미 있으면 생략
.venv/bin/pip install -q jsonschema .
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"; export CPATH="$SDK/usr/include"; export LIBRARY_PATH="$SDK/usr/lib"
PYTHONPATH=impl .venv/bin/python -m unittest tests.test_object_storage_http_assessment -v
```

문서 안의 `.lnpl` 조각 전부를 독립적으로 재컴파일하려면:

```bash
.venv/bin/python scripts/check_doc_snippets.py
```

## 종합 판정

**판정 규칙(먼저 정하고 적용한다)**: 시나리오의 부족함이 이미 작동하는
하나의 형태(2a — presign-only, 본문이 런타임을 지나지 않음)로 우회되면
"close"다. 실제로 실행해서 거부/실패가 확인된 부족함만 "open an RFC"의
근거가 되고, 그 경우 **실패가 확인된 부족함만큼만** 최소 연산 집합을
적는다 — 확인되지 않은 부족함까지 포함한 더 넓은 집합을 권고하지 않는다.

**결과**: 시나리오 1(업로드 저장)·시나리오 2a(서명 URL 수신·바인딩)는
`capability http`로 이미 된다. 실패가 확인된 것은 둘이다 — 시나리오 2b
(워크플로 스스로 서명된 요청 생성)와 시나리오 2c(그 서명 URL로 실제
PUT까지 한 워크플로 안에서 체이닝). 두 실패 모두 issue #193 자신이 가장
작다고 짚은 설계(presign-only, 본문이 런타임을 지나지 않음)의 **바깥쪽**에
있다 — 그 설계가 요구하는 것은 "서명 URL을 받아 바인딩"뿐이고, 이는 이미
된다. 따라서 **close — http로 충분하다**: 이 세 시나리오의 실패는 모두
issue #193이 가장 작다고 짚은 경로 밖에서만 나왔고, 그 경로 자체는 이미
작동한다. 2b/2c가 막는 것(워크플로 자신이 서명하거나, 서명 URL로 실제
업로드까지 체이닝하는 것)이 실제로 필요해지면, 그때 다시 2~3개의 구체적
요구사항과 함께 이 판정을 재검토한다 — 지금은 그 요구를 가리키는 실행
증거가 없다.
