# 09 — Purity (D12 repo-suite isolation + 잔존 파일 확인)

## D12 — 레포 게이트가 이 케이스에 닿지 않음

레포 게이트는 `python -m unittest discover -s impl/tests -t impl`이다(README/ci.yml).
그 discovery가 `qa/` 아래로 내려가지 않는다는 것을 워크트리 루트에서 직접 실행해 확인:

```
$ python3.13 -c "import unittest; s=unittest.TestLoader().discover('impl/tests', top_level_dir='impl'); print(s.countTestCases())"
3770
```

```
$ grep -rl s5-baseline impl/tests
(0 hits)
```

케이스 로컬 `pytest.ini`(`testpaths = tests`, `pythonpath = src`)는 케이스 디렉터리
안에서 `pytest`를 실행할 때만 스코프를 좁히는 것이지 상위 discovery를 막는 장치가
아니다 — 실제 격리는 레포 게이트가 애초에 `impl/tests`만 본다는 사실 자체다.

## 잔존 파일 확인

```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s5-baseline-fastapi/'
(0 lines — 케이스 디렉터리 밖에 어떤 변경/미추적 파일도 없음)

$ git status --porcelain -uall | grep -c '\.venv-s5'
0   (venv가 git에 잡히지 않음 — .gitignore로 제외됨)

$ find qa/probe-v0.8/cases/s5-baseline-fastapi -name '*.lnpl' | wc -l
0   (.lnpl 파일 없음 — 대조군 조건대로 lnpl 미사용)
```

`.claude/tmp/`는 세션 중 스냅샷(`src-pre-r10`)과 curl 로그를 담았다가 각 단계에서
증적으로 옮긴 뒤 삭제해 비어 있다.
