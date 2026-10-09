# Cloud — 문서 인덱스

클라우드 자원 프로비저닝(redis·postgres)·서빙 토폴로지·관측 내보내기·시크릿과
설정·무중단 스키마 변경·이벤트 전달 보장.

| 문서 id | load when |
|---------|-----------|
| `cloud-redis-cache-provisioning` | `capability redis`를 프로비저닝할 때 / 캐시 용량·축출 정책을 정할 때 / 캐시 장애 시 동작을 정할 때 / capability redis / cache eviction / provisioning |
| `cloud-postgres-provisioning` | postgres 백엔드를 붙일 때 / postgres 백엔드에 rate limit을 얼마로 / 처리량 상한·커넥션 수·max_connections를 잡을 때 / attach postgres / postgres backend / throughput ceiling / hold / rate limit / max_connections |
| `cloud-serving-topology` | 운영 호스트로 `lnpl serve`와 gunicorn 중 하나를 고를지 / gunicorn 워커 수·워커 클래스 / 인스턴스 수와 TLS 종단 프록시 / lnpl serve / gunicorn workers / worker class / reverse proxy / tls / nginx |
| `cloud-observability-export` | 관측 신호(trace·메트릭·접속로그)를 내보낼 때 / 메트릭 수집·헬스 프로브 / traces / trace exporter / otlp / access log / --log-format / metrics scrape / prometheus / healthz / readyz |
| `cloud-secrets-and-config` | 시크릿을 파일로 주입할 때 / 시크릿 원천(환경변수·파일·프로바이더) / 시크릿 교체 / lnpl.toml 프로필 / secrets / LNPL_JWT_SECRET_FILE / vault / rotation / lnpl.toml / profile |
| `cloud-schema-change-rollout` | 무중단 스키마 변경 순서 / 스키마 변경 배포 / 백업·복원 / schema change rollout / expand migrate contract / zero-downtime / backup restore / pitr |
| `cloud-event-delivery` | outbox·relay 전달 보장 / 이벤트 전달 보장·중복 수신 / 멱등 소비자 / outbox guarantee / outbox relay / at-least-once / idempotent consumer / dead-letter |
