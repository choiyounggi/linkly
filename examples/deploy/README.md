# 참조 Dockerfile — WSGI 운영 기동 (issue #87)

`examples/deploy/Dockerfile`은 `lnpl.wsgi:build_app()`(issue #80)을
gunicorn으로 띄우는 참조 컨테이너다. 이 저장소의 CI/릴리스 이미지가 아니라
— 그런 파이프라인은 없다(`docs/RELEASING.md`) — 운영자가 실제 배치에
시작점으로 삼을 수 있는, **실측된** 절차다.

## 무엇을 서빙하는가

`examples/linkhub.lnpl`을 `LNPL_BACKEND=fake`(요청마다 시딩되는 인메모리
저장소 — 계약은 `docs/serving.md` "계약 한계")로 서빙한다. 영속 저장소가
필요하면 `LNPL_BACKEND=sqlite:/path/to.db`로 바꾼다(`docs/backends.md`).
전체 환경 변수 계약(`LNPL_SOURCE`/`LNPL_BACKEND`/`LNPL_JWT_SECRET_ENV`/
`LNPL_CLOCK`)은 `docs/serving.md` "운영 배치" 절이 정본이다 — 이 Dockerfile은
그 계약을 소비할 뿐 재정의하지 않는다.

## 빌드

빌드 컨텍스트는 `examples/deploy/`(이 Dockerfile과 `.dockerignore`가 쓰는
1차 컨텍스트)이고, `impl/`·`examples/*.lnpl`·`pyproject.toml` 등 실제
소스는 저장소 루트를 가리키는 2차 named build context(`repo`)로 끌어온다
(Docker 23+/buildx `--build-context`) — 저장소 루트 전체를 컨텍스트로
보내지 않기 위해서다. 저장소 루트에서:

```bash
docker build -f examples/deploy/Dockerfile --build-context repo=. \
  -t linkly-deploy-smoke examples/deploy
```

## 실행 + 스모크 테스트

```bash
docker run -d --rm -p 8000:8000 --name linkly-deploy-smoke-run linkly-deploy-smoke

curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:8000/link-hub-service/save-bookmark \
  -H "Authorization: Bearer any" \
  -d '{"id":"3f2504e0-4f89-41d3-9a0c-0305e82c3301","url":"https://example.com/a",
       "title":"Example","owner":"3f2504e0-4f89-41d3-9a0c-0305e82c3302",
       "savedAt":"2026-08-24T09:00:00Z","visits":0}'
# -> 200

curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/no/such/path
# -> 404

docker stop linkly-deploy-smoke-run   # --rm이 컨테이너를 정리한다
docker rmi linkly-deploy-smoke
```

## 자동 스모크 테스트

위 build/run/curl 절차는 `test_deploy.py`로도 자동화되어 있다 — docker
build 1회 + 컨테이너 3개(케이스별)로 200(save-bookmark 완료)/404(미등록
경로)/400(파싱 불가 body) 세 경로를 검증하고 정리한다:

```bash
.venv/bin/python -m unittest discover -s examples/deploy -p "test_*.py" -v
```

`docker`가 PATH에 없으면 스킵된다(CI 등 컨테이너 런타임이 없는 환경).

## 실측 로그 (2026-08-24, Docker 27.4.0 / buildx 0.19.2, 이 저장소에서 실행)

빌드는 한 번에 통과하지 않았다 — 첫 시도는 `pyproject.toml`의
`license = { file = "LICENSE" }`가 참조하는 `LICENSE`를 builder 스테이지에
COPY하지 않아 hatchling 메타데이터 생성이 실패했고, 두 번째 시도는
`force-include`가 참조하는 `mlir/`·`kb/`(#60, wheel 데이터 파일 계약)를
COPY하지 않아 같은 방식으로 실패했다. 최종 Dockerfile은 `pyproject.toml`·
`README.md`·`LICENSE`·`impl/`·`mlir/`·`kb/`를 builder 스테이지에 전부
COPY한다 — 이 다섯이 `pip wheel --no-deps .`가 실제로 읽는 입력 전부다.

```
$ docker build -f examples/deploy/Dockerfile --build-context repo=. \
    -t linkly-deploy-smoke examples/deploy
...
 => [builder 5/5] RUN pip wheel --no-deps --wheel-dir /wheels .
    Building wheel for lnpl (pyproject.toml): finished with status 'done'
    Created wheel for lnpl: filename=lnpl-0.5.0-py3-none-any.whl size=255138 ...
 => [stage-1 4/5] RUN pip install --no-cache-dir /tmp/*.whl gunicorn && rm -rf /tmp/*.whl
    Successfully installed attrs-26.1.0 gunicorn-26.1.0 jsonschema-4.26.0
    jsonschema-specifications-2025.9.1 lnpl-0.5.0 referencing-0.37.0 rpds-py-2026.6.3
 => naming to docker.io/library/linkly-deploy-smoke:latest

$ docker run -d --rm -p 18100:8000 --name linkly-deploy-smoke-run linkly-deploy-smoke
$ docker logs linkly-deploy-smoke-run
[INFO] Starting gunicorn 26.1.0
[INFO] Listening at: http://0.0.0.0:8000 (1)
[INFO] Using worker: sync
[INFO] Booting worker with pid: 7

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18100/link-hub-service/save-bookmark \
    -H "Authorization: Bearer any" -d '{"id":"3f2504e0-...","url":"https://example.com/a", ...}'
200

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18100/no/such/path
404

$ docker stop linkly-deploy-smoke-run && docker rmi linkly-deploy-smoke
# both cleaned up — no container or image left afterward
```

200/404는 `docs/serving.md` 상태코드 매핑표의 M9(완료)/M1(미등록 경로)과
같은 판정이며, `docs/serving.md`가 gunicorn 아래에서 이미 고정한
200/404(`shorten-service` 예제)와 같은 성질을 `linkhub` 서비스에 대해
재확인한다.

## 이 참조가 다루지 않는 것

CI, 이미지 레지스트리 push, k8s 매니페스트는 이 이슈의 범위 밖이다
(#87 out-of-scope — 후속 이슈로 남는다). TLS 종단·워커 풀 관리는
`docs/serving.md`가 이미 명시한 대로 gunicorn(+ 필요하면 nginx)의 책임이지
이 Dockerfile의 책임이 아니다.
