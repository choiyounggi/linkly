# linkly

이 파일은 **라우팅만** 한다. 어휘·문법·RFC 규칙의 정본은 각 스킬과 `rfcs/`에 있다.

## 스킬 라우팅

플러그인 셋이 대상이 다르다 — `lnpl`은 `.lnpl`을 쓰는 쪽, `lnpl-dev`는 linkly 자체를
만드는 쪽, `lnpl-mcp`는 컴파일러를 셸이 아니라 MCP 툴로 부르는 쪽이다.

| 지금 하려는 일 | 스킬 |
|----------------|------|
| 환경 세팅 / 스위트 실행 / 다른 세션이 실행할 태스크 명세 작성 | `lnpl-dev-env` **(항상 먼저)** |
| `.lnpl`에서 아키텍처·이름·성능·보안·테스트·동시성·DB·클라우드를 **선택** | `lnpl-kb` → `lnpl-authoring` |
| `.lnpl` 작성·수정·리뷰 | `lnpl-authoring` |
| `spec` 블록 작성·리뷰 | `lnpl-spec` |
| `rfcs/`에 RFC 추가·개정·재번호·리뷰 | `lnpl-dev-rfc` |
| 뮤테이션 하네스 실행·해석 | `lnpl-dev-mutation` |
| 변경을 "됐다/완료"라고 말하기 직전 | `lnpl-verify` **(게이트)** |
| `lnpl` CLI 없음 / 진단 훅 조용함 / 버전 어긋남 | `lnpl-doctor` |

`.lnpl`은 **한 줄이라도 쓰기 전에** `lnpl-authoring`으로 간다. 어휘가 닫혀 있고
학습 데이터에 없어서, 그럴듯한 낱말은 파싱에 성공하고 런타임이 아무것도 하지 않는다.

### 플러그인이 설치되지 않은 세션

스킬 이름으로 호출되지 않으면 파일을 직접 읽는다. 내용은 같다.

```
plugins/lnpl/skills/{lnpl-authoring,lnpl-kb,lnpl-spec,lnpl-verify,lnpl-doctor}/SKILL.md
plugins/lnpl-dev/skills/{lnpl-dev-env,lnpl-dev-rfc,lnpl-dev-mutation}/SKILL.md
```

`lnpl-authoring`은 `references/` 아래 5개(`verbs` / `declarations` / `types` /
`grammar` / `spec`)로 다시 라우팅한다. 그 참조들은 컴파일러 테이블에서 **생성된**
산출물이다. 소스와 어긋난 것 같으면 추측하지 말고 기계로 확인한다:

```bash
python scripts/gen_plugin_references.py --check   # exit 1이면 재생성이 필요하다
```

(`lnpl-doctor`는 CLI 설치·버전을 본다. 참조 drift는 보지 않는다.)

## 스위트를 돌리기 전에

```bash
bash scripts/dev_doctor.sh
```

exit 0이면 준비된 것이다. 아니면 출력에 적힌 조치를 그대로 따른다.
전제조건 넷은 **전부 조용히 실패하고**, 그 실패가 원인을 가리키지 않아서
코드 회귀로 오독하기 쉽다. 상세는 `lnpl-dev-env`.

모드 B(MLIR/LLVM) 테스트가 대량으로 깨지는 것(실측 7 failures / 62 errors)은
`main`에서도 똑같이 재현되는 **환경 문제이지 회귀가 아니다.**

## RFC를 고칠 때

Accepted RFC는 직접 편집하지 않는다. **Supersedes**(통째로 대체) 또는
**Updates**(지정한 섹션만 개정, 상태는 Accepted 유지) 중 변경 크기에 맞는 쪽을 쓴다.
정본은 `rfcs/0007-rfc-process-v2.md`, 기계 검사는 `scripts/rfc_lint.py`, 절차는
`lnpl-dev-rfc`.

## 워크트리·병렬 세션

워크트리마다 **자기 `.venv`**를 만들고 **상대경로** `.venv/bin/python`으로 부른다.
메인 체크아웃의 venv를 절대경로로 공유하면 가드레일에 막힌다. 상세는 `lnpl-dev-env`.

## 임시 파일

`/tmp`나 시스템 임시 디렉터리를 쓰지 않는다. `.claude/tmp/`를 쓴다.
테스트가 만든 빌드 작업 디렉터리는 남기지 않는다.
