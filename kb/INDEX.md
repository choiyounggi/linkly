# Knowledge Base — 루트 라우팅 인덱스

이 파일과 각 카테고리의 `index.md`가 **1단 라우팅 계층**이다(RFC-0005 §Repository
Layout & Routing). 에이전트는 여기서 트리거를 매칭해 문서 id만 얻고, 본문은 매칭된
뒤에만 로드한다 — 3단 progressive disclosure의 1단이다.

| Category | route here when |
|----------|-----------------|
| [Architecture](architecture/index.md) | 서비스·모듈 경계와 계층 구조 등 시스템 구조 결정 |
| [Naming](naming/index.md) | entity·필드·워크플로 등 식별자 명명 규약 |
| [Performance](performance/index.md) | 응답 예산·캐싱·쿼리 비용 등 성능 목표 달성 |
| [Security](security/index.md) | 인증·인가·토큰·비밀값 취급 등 보안 결정 |
| [Testing](testing/index.md) | 테스트 수준·케이스 최소셋·검증 가능성 기준 |
| [Concurrency](concurrency/index.md) | 병렬 실행·fan-out/merge·경쟁 상태 회피 |
| [Database](database/index.md) | 스키마·인덱스·트랜잭션 등 데이터 저장 결정 |
| [Cloud](cloud/index.md) | 클라우드 자원 프로비저닝·배포 대상 선택 |
| [Patterns](patterns/index.md) | 재사용 가능한 검증된 구현 패턴 |
| [AntiPatterns](antipatterns/index.md) | 반복 실패로 확인된 회피 대상 패턴 |
| [Style](style/index.md) | 코드·선언 표기 스타일 규약 |
| [Framework](framework/index.md) | 프레임워크·Capability 바인딩별 사용 지침 |
