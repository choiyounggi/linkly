---
name: lnpl-doctor
description: Use when the lnpl CLI is missing, the .lnpl diagnostics hook is silent, `lnpl` commands fail, or the plugin and the installed CLI may have drifted apart in version. Diagnoses installation and version mismatch for the linkly platform.
---

# lnpl 설치 진단

플러그인이 설치돼 있어도 `lnpl` CLI가 없으면 진단 훅이 조용히 꺼져 있게 된다.
어휘 문서는 특정 커밋의 소스에서 생성된 산출물이라, CLI 버전이 어긋나면 문서가
실제 동작과 다른 것을 가르칠 수 있다.

## 진단 실행

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh
```

exit 0이면 이상 없음. exit 1이면 출력에 적힌 조치를 그대로 따른다.

## 무엇을 보는가

| 항목 | 문제일 때의 뜻 |
|------|-----------------|
| CLI 경로 | `lnpl`이 PATH에 없다 → 진단 훅이 전부 꺼져 있다 |
| CLI 버전 | `--version`을 모른다 → 구버전 설치다 |
| 플러그인 버전 | CLI와 다르다 → 어휘 문서가 실제 동작과 어긋날 수 있다 |
| 컴파일 | 최소 예제도 실패한다 → 설치가 손상됐다 |

## 설치

linkly 체크아웃에서:

```bash
pip install /path/to/linkly
```

설치 없이 레포 안에서만 쓸 거라면:

```bash
PYTHONPATH=impl python -m lnpl compile <파일>
```

이 경우 `lnpl`이 PATH에 없으므로 진단 훅은 계속 꺼져 있다.
