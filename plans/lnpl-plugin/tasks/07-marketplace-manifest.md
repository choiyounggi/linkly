# Task 07: 마켓플레이스 매니페스트 — 레포를 설치 가능한 플러그인 소스로 만든다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
`/plugin marketplace add choiyounggi/linkly` → `/plugin install lnpl@linkly`로
설치되게 만든다. 앞선 태스크들이 만든 스킬 2종·훅 1종을 하나의 플러그인으로 묶는
마지막 조각이다.

## Files
- Create: `.claude-plugin/marketplace.json` (레포 루트)
- Create: `plugins/lnpl/.claude-plugin/plugin.json`
- Create: `plugins/lnpl/README.md`
- Create: `impl/tests/test_plugin_manifest.py`
- Modify: `README.md` (설치 안내 절 추가)

## Interfaces
- Consumes: Task 04(`skills/lnpl-authoring/`), Task 05(`hooks/hooks.json`),
  Task 06(`skills/lnpl-doctor/`, `scripts/doctor.sh`)
- Produces: 설치 가능한 플러그인. 이 태스크 이후 `doctor.sh`의 버전 비교가 실제로
  작동한다(Task 06까지는 `plugin.json`이 없어 건너뛰었다).

## References
- `~/.claude/plugins/marketplaces/groundwork/.claude-plugin/marketplace.json` —
  같은 소유자가 이미 검증한 구조. `"source": "./plugins/<name>"`으로 레포 내
  하위 디렉터리를 가리킨다.
- `plans/lnpl-plugin/plan.md` A2 — 제품 레포가 마켓플레이스를 겸하는 근거
  (tracked 2.1MB / packed 621KB라 클론 비용이 없다).
- A12 — `plugin.json`의 `version`은 `lnpl.__version__`을 따른다.

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_plugin_manifest.py`:

```python
"""마켓플레이스·플러그인 매니페스트의 정합 검사.

레포가 제품이면서 동시에 마켓플레이스다. 매니페스트가 가리키는 경로가
실재하지 않으면 설치는 되고 아무것도 로드되지 않는다 — 조용한 실패라
테스트로 고정한다.
"""
import json
import os
import subprocess
import unittest

import lnpl

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKET = os.path.join(REPO, ".claude-plugin", "marketplace.json")
PLUGIN_DIR = os.path.join(REPO, "plugins", "lnpl")
PLUGIN_JSON = os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class MarketplaceTest(unittest.TestCase):
    def test_marketplace_manifest_exists_and_parses(self):
        self.assertTrue(os.path.isfile(MARKET))
        self.assertIsInstance(load(MARKET), dict)

    def test_marketplace_declares_one_plugin_named_lnpl(self):
        entries = load(MARKET)["plugins"]
        self.assertEqual([e["name"] for e in entries], ["lnpl"])

    def test_marketplace_source_resolves_to_a_real_directory(self):
        entry = load(MARKET)["plugins"][0]
        resolved = os.path.normpath(os.path.join(REPO, entry["source"]))
        self.assertTrue(os.path.isdir(resolved),
                        "source가 실재하지 않는다: %s" % entry["source"])
        self.assertEqual(resolved, os.path.normpath(PLUGIN_DIR))

    def test_marketplace_has_an_owner(self):
        self.assertIn("name", load(MARKET)["owner"])


class PluginManifestTest(unittest.TestCase):
    def test_plugin_manifest_exists_and_parses(self):
        self.assertTrue(os.path.isfile(PLUGIN_JSON))
        self.assertIsInstance(load(PLUGIN_JSON), dict)

    def test_plugin_name_matches_the_marketplace_entry(self):
        self.assertEqual(load(PLUGIN_JSON)["name"],
                         load(MARKET)["plugins"][0]["name"])

    def test_plugin_version_tracks_the_package_version(self):
        # A12: 버전 단일 출처는 lnpl.__version__이다.
        self.assertEqual(load(PLUGIN_JSON)["version"], lnpl.__version__)

    def test_marketplace_entry_version_matches_plugin_manifest(self):
        self.assertEqual(load(MARKET)["plugins"][0]["version"],
                         load(PLUGIN_JSON)["version"])

    def test_plugin_description_is_substantive(self):
        self.assertGreater(len(load(PLUGIN_JSON)["description"]), 60)


class PluginContentsTest(unittest.TestCase):
    REQUIRED = (
        os.path.join("skills", "lnpl-authoring", "SKILL.md"),
        os.path.join("skills", "lnpl-doctor", "SKILL.md"),
        os.path.join("hooks", "hooks.json"),
        os.path.join("hooks", "lnpl-diagnostics.sh"),
        os.path.join("scripts", "doctor.sh"),
        "README.md",
    )

    def test_every_declared_component_is_present(self):
        for rel in self.REQUIRED:
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN_DIR, rel)),
                            "플러그인에 %s가 없다" % rel)

    def test_shell_entrypoints_are_executable(self):
        for rel in (os.path.join("hooks", "lnpl-diagnostics.sh"),
                    os.path.join("scripts", "doctor.sh")):
            self.assertTrue(os.access(os.path.join(PLUGIN_DIR, rel), os.X_OK),
                            "%s에 실행 권한이 없다" % rel)

    def test_doctor_now_compares_versions_and_agrees(self):
        # Task 06까지는 plugin.json이 없어 비교를 건너뛰었다. 이제 실제로 비교한다.
        env = dict(os.environ)
        env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env["PATH"]
        env["PYTHONPATH"] = os.path.join(REPO, "impl")
        env["CLAUDE_PLUGIN_ROOT"] = PLUGIN_DIR
        proc = subprocess.run(["bash", os.path.join(PLUGIN_DIR, "scripts", "doctor.sh")],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(lnpl.__version__, proc.stdout)
        self.assertNotIn("건너뜀", proc.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_manifest -v 2>&1 | tail -12
```
Expected: FAIL — `marketplace.json`이 없다.

- [ ] **Step 3: `plugin.json`을 만든다**

`plugins/lnpl/.claude-plugin/plugin.json`:

```json
{
  "name": "lnpl",
  "description": "Write `.lnpl` for the linkly LLM-native platform. LNPL's vocabulary is closed and absent from model training data, so a plausible-looking source compiles and then silently does nothing — an unknown verb derives no effect, and most declarations are never enforced. This plugin routes the model to the vocabulary generated from the compiler's own tables, and surfaces `lnpl compile` diagnostics the moment a file is written.",
  "version": "0.2.0",
  "author": {
    "name": "choiyounggi",
    "url": "https://github.com/choiyounggi"
  },
  "homepage": "https://github.com/choiyounggi/linkly",
  "strict": false
}
```

`version`은 `lnpl.__version__`과 같아야 한다. Step 1의
`test_plugin_version_tracks_the_package_version`이 어긋남을 잡는다.

- [ ] **Step 4: `marketplace.json`을 만든다**

`.claude-plugin/marketplace.json`:

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "linkly",
  "description": "linkly — an LLM-native programming platform: a language, a semantic IR, a native compiler, a runtime, a knowledge base, and an agent protocol.",
  "owner": {
    "name": "choiyounggi",
    "url": "https://github.com/choiyounggi"
  },
  "plugins": [
    {
      "name": "lnpl",
      "description": "Authoring support for `.lnpl` — closed-vocabulary routing generated from the compiler's own tables, plus write-time compile diagnostics.",
      "category": "development",
      "author": {
        "name": "choiyounggi",
        "url": "https://github.com/choiyounggi"
      },
      "source": "./plugins/lnpl",
      "homepage": "https://github.com/choiyounggi/linkly",
      "version": "0.2.0",
      "tags": ["lnpl", "linkly", "dsl", "compiler", "authoring", "claude-code"]
    }
  ]
}
```

- [ ] **Step 5: 플러그인 README를 쓴다**

`plugins/lnpl/README.md`:

````markdown
# lnpl — Claude Code plugin

`.lnpl` 소스를 쓰는 동안 linkly의 닫힌 어휘로 라우팅하고, 저장 직후 컴파일 진단을
되돌린다.

## 왜 필요한가

LNPL의 어휘는 닫혀 있고 모델의 학습 데이터에 없다. 그래서 그럴듯한 파일이
**컴파일에 성공한 뒤 아무 일도 하지 않는** 결과가 흔하다:

- `VERB_LEXICON` 밖의 동사는 에러가 아니라 효과 없는 no-op이다 (issue #36)
- `security jwt`·`policy rollback`은 선언돼도 집행되지 않는다 (issue #38)
- `if` / `for` / `while` / `switch`는 문법적으로 표현 불가능하다

`lnpl compile`은 이것들을 진단으로 알려주지만 **stderr에 쓰고 종료 코드 0으로
끝난다** — 보지 않으면 사라진다.

## 구성

| 구성요소 | 하는 일 |
|----------|---------|
| `lnpl-authoring` 스킬 | 어휘 라우팅. 본문은 컴파일러 테이블에서 생성된 `references/` |
| `lnpl-doctor` 스킬 | 설치·버전 불일치 진단 |
| PostToolUse 훅 | `*.lnpl` 저장 직후 `lnpl compile` 진단을 모델에게 전달 |

어휘 문서는 `scripts/gen_plugin_references.py`의 산출물이고, 손으로 고치면
`impl/tests/test_plugin_references.py`가 실패한다. 정본은 언제나 소스다.

## 설치

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl@linkly
```

훅이 동작하려면 `lnpl` CLI가 PATH에 있어야 한다:

```bash
pip install /path/to/linkly
```

문제가 있으면 `lnpl-doctor` 스킬을 쓴다.
````

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_manifest -v 2>&1 | tail -15
```
Expected: PASS (13 tests)

- [ ] **Step 7: 매니페스트가 실제로 로드되는지 확인한다**

```bash
claude plugin validate . 2>&1 | tail -20 || \
  jq -e '.plugins[0].source' .claude-plugin/marketplace.json && \
  jq -e '.name, .version' plugins/lnpl/.claude-plugin/plugin.json
```
Expected: `claude plugin validate`가 있으면 그 결과를, 없으면 `jq`가 두 매니페스트를
파싱해 값을 출력한다.

- [ ] **Step 8: 루트 README에 설치 안내를 추가한다**

`README.md`의 사용법 절(현재 146행 근처 `PYTHONPATH=impl` 안내) **뒤에** 다음을 넣는다:

````markdown
### Claude Code plugin

`.lnpl`을 쓸 때 Claude가 닫힌 어휘로 라우팅되고, 저장 직후 컴파일 진단을 받게 하려면:

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl@linkly
```

훅이 동작하려면 `lnpl`이 PATH에 있어야 한다 — `pip install .`.
자세한 내용은 [plugins/lnpl/README.md](plugins/lnpl/README.md).

> 개발자용: 테스트 스위트도 `.venv`에 `lnpl` 콘솔 스크립트가 있어야 전부 통과한다
> (훅·doctor 테스트가 `command -v lnpl`로 CLI를 찾는다). venv를 만든 뒤
> `.venv/bin/pip install .`을 한 번 돌려라. `impl/lnpl/`을 고친 뒤에는
> `pip install --force-reinstall --no-deps .`로 재설치한다.
````

- [ ] **Step 9: 전체 스위트 무회귀 + 골든 무변경 확인**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
git status --porcelain examples/
```
Expected: `OK`, 그리고 `examples/`에 변경 0건(수용 기준 6).

- [ ] **Step 10: 커밋**

```bash
git add .claude-plugin/ plugins/lnpl/.claude-plugin/ plugins/lnpl/README.md \
        impl/tests/test_plugin_manifest.py README.md
git commit -m "feat(plugin): publish linkly as a marketplace hosting the lnpl plugin

제품 레포가 마켓플레이스를 겸한다. tracked 2.1MB라 클론 비용이 없고,
무엇보다 스킬과 lower.py가 같은 커밋에 묶여서 어휘가 구조적으로 갈라설 수
없다 — 별도 레포였다면 동기화 장치를 따로 지어야 한다."
```

## Deliverables
- `.claude-plugin/marketplace.json`
- `plugins/lnpl/.claude-plugin/plugin.json`
- `plugins/lnpl/README.md`
- `impl/tests/test_plugin_manifest.py` — 13건
- `README.md` 설치 안내 절

## Acceptance
1. 두 매니페스트가 유효한 JSON이고, `source`가 실재하는 디렉터리로 해석된다.
2. 플러그인 이름이 마켓플레이스 항목과 일치하고, 두 버전이 `lnpl.__version__`과 같다.
3. 선언한 구성요소 6종이 전부 실재하고, 셸 진입점 2종에 실행 권한이 있다.
4. `doctor.sh`가 이제 버전을 실제로 비교하고 통과한다("건너뜀"이 출력되지 않는다).
5. `examples/` 무변경.
6. 전체 스위트 무회귀.
