# lnpl-dev — Claude Code plugin (linkly 기여자용)

`.lnpl`을 **쓰는** 사람이 아니라 linkly 플랫폼 자체를 **고치는** 사람을 위한 플러그인이다.
`.lnpl` 작성 지원은 [`lnpl`](../lnpl/README.md) 플러그인이다.

## 왜 필요한가

이 레포에서 반복해 시간을 먹는 세 가지가 있고, 셋 다 **조용히 실패한다**:

- **환경 전제 넷** — python3.13, venv의 `jsonschema`, venv의 `lnpl` 콘솔 스크립트,
  LLVM 툴체인 + `CPATH`/`LIBRARY_PATH`. 빠뜨리면 테스트가 실패하는데 그 실패가
  원인을 가리키지 않아 코드 회귀로 오독된다
- **RFC 프로세스** — 번호 재사용 금지, 고정 7섹션, 상태 어휘. 과거에 두 문서가
  같은 번호를 주장한 적이 있다
- **뮤테이션 스윕** — 20분+, 리터럴 앵커, 파이프에 가려지는 종료 코드, 그리고
  복사 목록이 낡으면 77개 뮤턴트가 전부 똑같이 실패한다

## 구성

| 스킬 | 언제 |
|------|------|
| `lnpl-dev-env` | 스위트를 돌리기 전, 무관해 보이는 실패를 만났을 때, 새 워크트리, 남에게 넘길 태스크를 쓸 때 |
| `lnpl-dev-rfc` | RFC를 추가·개정·번호 재배정·리뷰할 때 |
| `lnpl-dev-mutation` | 뮤테이션 스윕을 돌리거나 해석할 때, 새 레포 경로를 읽는 테스트를 추가한 뒤 |

도구는 레포의 `scripts/`에 있다 — 기여자는 언제나 체크아웃을 갖고 있으므로
플러그인은 "언제 쓰는가"만 담는다:

```
bash scripts/dev_doctor.sh      # 환경 전제 넷을 진단
python scripts/rfc_lint.py      # RFC-0007의 기계적 조항을 검사
```

`rfc_lint.py`는 테스트 스위트에 걸려 있지 않다. 검사 **로직**은
`impl/tests/test_rfc_lint.py`가 합성 입력으로 검증하지만, 레포의 RFC가 깨끗한지는
게이트하지 않는다 — 빠진 섹션을 채우는 일은 도구가 강제할 사안이 아니다.

## 설치

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl-dev@linkly
```
