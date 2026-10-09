# 릴리스 절차

PR 게이트와 태그 릴리스는 `.github/workflows/ci.yml`·`release.yml`로
자동화되어 있다(issue #141; 그 전 v0.1.0–v0.5.0은 issue #87 시점 기준 전부
수동 절차였다). 이 문서는 그 자동화가 대신하지 않는 나머지 단계(버전 bump,
CHANGELOG, 릴리스 노트 본문)와, 자동화가 실패했을 때의 로컬 재현·수동 폴백을
순서대로 고정한다.

## 절차

1. **완료 게이트를 통과시킨다.** PR과 `main` push마다 `ci.yml`이 자동으로
   돌린다. 로컬 재현(`main`에서):
   ```
   bash scripts/dev_doctor.sh
   PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl \
     2>&1 | grep -E "^(OK|FAILED|Ran )"
   .venv/bin/python scripts/rfc_lint.py
   .venv/bin/python scripts/gen_plugin_references.py --check
   .venv/bin/python scripts/check_version_sync.py
   ```
   전부 통과해야 한다. 실패하면 릴리스하지 않는다.

2. **버전을 올린다.** `pyproject.toml`의 `[project] version`을 새 버전으로
   바꾼다(0.x이므로 [docs/compatibility.md](compatibility.md)의 breaking
   여부와 무관하게 minor 자리를 올려 왔다 — 지금까지의 실제 이력).

   릴리스 태그를 push한 직후, `main`의 버전을 다음 릴리스를 가리키는
   `X.Y.(Z+1).dev0`로 올려 두는 것을 권장한다(예: `v0.8.0` 태그 뒤
   `0.9.0.dev0`) -- 태그와 태그 사이의 모든 빌드가 직전 릴리스와 같은
   버전 문자열을 내는 것을 막는다(issue #205). `.dev0` 접미사가 붙어도
   네 지점(`pyproject.toml`/`impl/lnpl/__init__.py`/`plugins/*/plugin.json`/
   `marketplace.json`) 모두 같은 한 문자열이면 되므로 `scripts/
   check_version_sync.py`는 그대로 통과한다. 이 절차 자체는 현재 범위
   밖이다 -- 이번 태스크는 권장 문구만 남긴다.

3. **`CHANGELOG.md`를 갱신한다.** `## [Unreleased]`의 내용을 새
   `## [x.y.z] — <발행일>` 절로 옮기고(제목·날짜는 5단계에서 만들 GitHub
   Release와 맞춘다), 각 항목이 어느 이슈/PR을 닫는지 남긴다. breaking
   change는 `### Changed` 아래, [docs/compatibility.md](compatibility.md)의
   어느 계약을 건드렸는지 이름을 대며 적는다. 문서 하단의 태그 링크
   목록에 새 버전 줄을 추가하고 `[Unreleased]` 링크의 비교 기준을 새
   태그로 옮긴다. 빈 `## [Unreleased]` 절을 새로 연다.

4. **커밋한다.** 버전 bump + CHANGELOG 갱신을 하나의 커밋으로.

5. **태그를 push하면 GitHub Release가 자동 발행된다.**
   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
   `release.yml`이 게이트 재실행 → `python -m build`로 sdist+wheel 빌드 →
   `gh release create`까지 수행한다. 같은 태그 push가 `image` 잡도 깨운다
   (issue #190): `docker/Dockerfile`로 런타임 전용 이미지를 빌드하고,
   마운트한 소스로 `/-/healthz` 200을 받는 스모크를 통과한 뒤에만
   `ghcr.io/<owner>/linkly`에 `vX.Y.Z`와 `X.Y` 두 태그로 push한다
   (`latest`는 올리지 않는다). 베이스 이미지는 digest로 고정되어 있고,
   SBOM·provenance attestation이 함께 올라간다. 이 이미지는 코어
   런타임만 담는다 — `postgres`·`redis`·`otel` 드라이버
   (`lnpl-postgres`·`lnpl-redis`·`lnpl-otel`,
   [README.md](../README.md)의 "Real backend drivers" 절)는 기본
   이미지에 넣지 않고 사용자가 파생 이미지로 얹는 방식을 권장한다
   (issue #190 본문). 세 드라이버 모두 아직 PyPI에 없다(2026-10-05
   확인) — GitHub 소스 아카이브에서 설치한다:
   ```dockerfile
   FROM ghcr.io/<owner>/linkly@sha256:<digest>
   USER root
   RUN pip install --no-cache-dir --no-deps \
         "https://github.com/choiyounggi/lnpl-postgres/archive/refs/heads/main.tar.gz" \
       && pip install --no-cache-dir "psycopg[binary]>=3.2,<3.3"
   USER linkly
   ```
   `--no-deps`가 필수다: `lnpl-postgres`의 `pyproject.toml`이 `lnpl`
   의존성을 linkly의 특정 git 커밋으로 고정해 둬서, 그대로 두면 pip가
   이미지에 이미 설치된 `lnpl` 휠을 그 커밋으로 재설치하려
   한다(이 슬림 베이스에는 `git`도 없어 그 자체로 실패한다).
   `psycopg[binary]` 버전은 `lnpl-postgres`가 요구하는 범위
   (`>=3.2,<3.3`)로 맞춘다 — 비워 두면 최신 3.3.x가 설치되어 의존성
   충돌 경고가 난다. 위 레시피는 로컬에서 실측했다(`docker build`
   성공, 설치 후 `lnpl` 버전 불변, `/-/healthz` 여전히 200). PyPI
   발행은 아직 비활성이다(워크플로의 `publish-pypi` 잡 주석 참고 —
   Trusted Publisher 미등록, 사용자 결정으로 이번 단계 범위 밖).
   자동화가 실패하면 수동으로:
   ```
   gh release create vX.Y.Z --title "linkly vX.Y.Z — <한 줄 테마>" \
     --notes-file <CHANGELOG.md의 해당 절에서 뽑은 본문>
   ```
   Release 노트 본문은 3단계에서 이미 쓴 CHANGELOG 절과 같은 사실을
   말해야 한다 — 서로 다른 이야기를 하면 둘 중 하나가 소급 갱신 때
   틀린 근거가 된다(`gh release view vX.Y.Z`가 CHANGELOG 소급의
   유일한 근거이기 때문).

## 참고

- 컨테이너 이미지는 이제 `release.yml`의 `image` 잡이 같은 태그 push로
  발행한다(위 5단계, issue #190) — 운영 배치 매니페스트(k8s·nginx TLS
  등)는 여전히 릴리스 절차와 별개다:
  [examples/deploy/README.md](../examples/deploy/README.md)를 본다.
- 과거 5개 릴리스(v0.1.0–v0.5.0)의 소급 CHANGELOG 작성 근거는
  `gh release view <tag>`이며, [CHANGELOG.md](../CHANGELOG.md) 상단에
  같은 원칙이 적혀 있다.
- `ci.yml`의 `gate`·`release.yml`의 `gates`는 `impl/tests/test_repo_state.py`를
  discovery에서 모듈명으로 명시 제외한다 — 그 파일은 issue #35의 최외곽
  회귀라 mode B MLIR/LLVM 툴체인 없이는 무의미하고, 자기 docstring에 "never
  skips, on purpose"라고 적혀 있어 skipUnless 가드를 달지 않는다. 이 두 잡의
  러너에는 여전히 그 툴체인이 없어 제외가 남아 있지만, 더는 커버리지가
  비어 있지 않다: `ci.yml`의 `modeb-linux` 잡이 핀 버전 LLVM/MLIR 툴체인을
  설치하고 `test_repo_state`를 직접 돌린다(issue #161).
