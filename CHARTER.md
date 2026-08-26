# LLM Native Programming Platform (LNPP) — Project Charter

> 0단계 비전 문서. 정본 설계는 `rfcs/`의 RFC들이다. 이 문서는 원문 보존용으로 수정하지 않는다.

## Vision

인간 중심 프로그래밍 언어의 시대를 끝내고, LLM 중심의 소프트웨어 개발 플랫폼을 만든다.

기존 언어(Java, Go, Rust, C++, Python)는 사람이 작성하기 쉽도록 설계되었다.
하지만 앞으로는 대부분의 코드가 사람이 아니라 LLM에 의해 생성된다.

따라서 새로운 언어는 사람이 아닌 LLM이 가장 쉽게 이해하고,
가장 정확하게 추론하며,
가장 빠르게 최적화할 수 있도록 설계되어야 한다.

LNPP의 목표는 새로운 프로그래밍 언어 하나를 만드는 것이 아니라,

* Language
* Semantic IR
* Native Compiler
* Runtime
* Knowledge Base
* AI Development Pipeline

전체를 하나의 플랫폼으로 구축하는 것이다.

## 핵심 철학

### 1. Human First → AI First

기존 언어: 사람이 읽기 쉽다 → 컴파일러가 해석한다 → CPU가 실행한다.

LNPP: LLM이 이해하기 쉽다 → Semantic Engine이 분석한다 → Native Optimizer가 최적화한다 → CPU가 실행한다.

### 2. Code가 아니라 Intent를 작성한다

기존 언어: 어떻게 구현할 것인가(How)
새 언어: 무엇을 만들 것인가(What)

예시:

```
service UserService
goal
    authenticate user
    cache profile
    rollback on failure
    audit login
performance
    response < 50ms
security
    jwt
database
    postgres
```

구현은 Compiler와 AI가 결정한다.

### 3. Syntax보다 Semantic이 중요하다

`public class UserService` → `service UserService`

`if / for / while / switch` → `when / repeat / parallel / until / pipeline`

모든 문법은 사람이 아니라 LLM이 이해하기 쉽도록 설계한다.

## 목표

개발자는 요구사항 정의 / 비즈니스 규칙 정의 / 목표 정의만 수행한다.

Compiler와 AI는 Architecture 설계, 코드 생성, 테스트 생성, Benchmark, Optimization,
Refactoring, Documentation, Deployment까지 수행한다.

## Language Design

Entity:

```
entity User
field
    id UUID
    email Email
    password Password
    createdAt DateTime
```

Service: `service LoginService`

Workflow:

```
workflow Login
validate input
authenticate
cache user
generate token
audit login
return token
```

Event: `event UserCreated`

Policy:

```
policy
retry 3
rollback
timeout 3s
parallel
```

Security:

```
security
jwt
role admin
```

Performance:

```
performance
cache 5m
response < 30ms
parallel
prefetch
batch
```

## Semantic Type System

Primitive Type를 최소화한다.

기존: String, Long, boolean

새 언어: UUID, Money, Email, Phone, Password, Address, Image, File, Currency,
GeoLocation, Json, Html, Markdown

Semantic Type에는 Validation Rule이 포함된다.

예) Email → RFC Validation → 자동 Validation 생성 → OpenAPI 생성 → Frontend Validation 생성

## Semantic IR

AST를 버린다.

기존 AST: Assignment, BinaryExpression, BlockStatement, IfStatement

새 IR: BusinessRule, Validation, NetworkCall, RepositoryCall, CacheAccess,
Transaction, Authorization, Concurrency, Workflow, Pipeline

Compiler는 Semantic IR를 중심으로 동작한다.

## Runtime

목표: 최소 메모리 사용, GC 최소화, Zero Copy, Async Native, Event Driven,
Actor Model, Lock Free. 필요한 기능만 포함한다.

## Native Compiler

Source → Semantic Parser → Semantic IR → Architecture Optimizer →
Concurrency Optimizer → Memory Optimizer → LLVM IR → Native Binary

JVM은 존재하지 않는다.

## Knowledge Base

가장 중요한 구성 요소이다. Language보다 중요하다.

구성: Architecture Guide, Naming Guide, Performance Guide, Security Guide,
Testing Guide, Concurrency Guide, Database Guide, Cloud Guide, Patterns,
Anti Patterns, Style Guide, Framework Guide

모든 AI Agent는 동일한 KB를 사용한다.

## AI Pipeline

Planner → Architect → Coder → Reviewer → Tester → Performance Analyzer →
Security Auditor → Refactoring Agent → Release Agent

모든 Agent는 Semantic IR를 공유한다.

## Auto Generation

REST API, GraphQL, gRPC, Database, Migration, OpenAPI, Frontend SDK,
Unit Test, Integration Test, Benchmark, Docker, Kubernetes, CI/CD,
Monitoring, Alert

## Concurrency

언어 차원에서 지원한다.

```
parallel
fetch user
fetch permissions
fetch settings
merge
```

Thread를 직접 다루지 않는다.

## Memory Model

개발자는 Memory를 신경 쓰지 않는다. Compiler가 Stack, Heap, Arena, Pool을 자동 선택한다.

## Optimization

Compiler가 수행: Inline, Dead Code Elimination, Escape Analysis, SIMD,
Lock Elimination, Prefetch, Vectorization, Cache Optimization, Branch Prediction

## Observability

모든 프로그램은 기본적으로 Metrics, Trace, Log를 생성한다. 추가 코드가 필요 없다.

## Testing

언어 기본 기능:

```
spec Login
given
valid account
when
login
expect
status 200
token exists
```

Unit Test와 Integration Test를 자동 생성한다.

## Package Manager

Package는 Code가 아니라 Capability를 설치한다.

```
capability
postgres
redis
jwt
s3
kafka
```

Compiler가 필요한 구현체를 자동 선택한다.

## Framework

Framework를 제거한다. 언어 자체가 DI, Transaction, Validation, ORM, HTTP,
Security, Scheduling을 내장한다.

## Cloud Native

Docker, Kubernetes, Service Discovery, Config, Secret, Health Check, Metrics,
Autoscaling 자동 생성.

## LLM Friendly Design

모든 문법은 Predictable, Deterministic, Semantic, Low Ambiguity를 만족해야 한다.
LLM이 추론하기 쉬운 문법만 허용한다.

## 최종 목표

현재: Human → Java → Compiler → CPU

미래: Developer → Intent → LLM → Semantic IR → Native Optimizer → Machine Code → CPU

개발자는 구현을 작성하지 않는다. 목표와 비즈니스 규칙만 정의한다.
AI는 시스템 전체를 설계하고, 구현하고, 검증하고, 최적화하며, 배포한다.

LNPP는 단순한 새로운 프로그래밍 언어가 아니라, AI 시대를 위한 최초의
LLM Native Software Platform을 목표로 한다.
