# 릴리스 절차

이 저장소에 릴리스 파이프라인(CI/CD)은 없다 — 태그와 GitHub Release는
수동으로 만든다(issue #87 시점 기준: v0.1.0–v0.5.0 전부 이 절차). 이 문서는
그 수동 절차를 순서대로 고정한다.

## 절차

1. **완료 게이트를 통과시킨다.** `main`에서:
   ```
   bash scripts/dev_doctor.sh
   PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl \
     2>&1 | grep -E "^(OK|FAILED|Ran )"
   .venv/bin/python scripts/rfc_lint.py
   .venv/bin/python scripts/gen_plugin_references.py --check
   ```
   전부 통과해야 한다. 실패하면 릴리스하지 않는다.

2. **버전을 올린다.** `pyproject.toml`의 `[project] version`을 새 버전으로
   바꾼다(0.x이므로 [docs/compatibility.md](compatibility.md)의 breaking
   여부와 무관하게 minor 자리를 올려 왔다 — 지금까지의 실제 이력).

3. **`CHANGELOG.md`를 갱신한다.** `## [Unreleased]`의 내용을 새
   `## [x.y.z] — <발행일>` 절로 옮기고(제목·날짜는 5단계에서 만들 GitHub
   Release와 맞춘다), 각 항목이 어느 이슈/PR을 닫는지 남긴다. breaking
   change는 `### Changed` 아래, [docs/compatibility.md](compatibility.md)의
   어느 계약을 건드렸는지 이름을 대며 적는다. 문서 하단의 태그 링크
   목록에 새 버전 줄을 추가하고 `[Unreleased]` 링크의 비교 기준을 새
   태그로 옮긴다. 빈 `## [Unreleased]` 절을 새로 연다.

4. **커밋한다.** 버전 bump + CHANGELOG 갱신을 하나의 커밋으로.

5. **태그를 만들고 GitHub Release를 발행한다.**
   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "linkly vX.Y.Z — <한 줄 테마>" \
     --notes-file <CHANGELOG.md의 해당 절에서 뽑은 본문>
   ```
   Release 노트 본문은 3단계에서 이미 쓴 CHANGELOG 절과 같은 사실을
   말해야 한다 — 서로 다른 이야기를 하면 둘 중 하나가 소급 갱신 때
   틀린 근거가 된다(`gh release view vX.Y.Z`가 CHANGELOG 소급의
   유일한 근거이기 때문).

## 참고

- 배치·컨테이너 이미지 절차는 릴리스 절차와 별개다 —
  [examples/deploy/README.md](../examples/deploy/README.md)를 본다.
- 과거 5개 릴리스(v0.1.0–v0.5.0)의 소급 CHANGELOG 작성 근거는
  `gh release view <tag>`이며, [CHANGELOG.md](../CHANGELOG.md) 상단에
  같은 원칙이 적혀 있다.
