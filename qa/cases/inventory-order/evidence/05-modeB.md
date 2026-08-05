# evidence/05-modeB — MLIR→네이티브 컴파일·실행 (Task 05)

재시도 수: 1 (`--field` 키 형식 오인 1회 → 재실행으로 규명)
환경: export 4줄 적용(evidence/00), dev_doctor rc=0 상태. AGENTS.md의
"모드 B 대량 실패(7f/62e)"는 이 케이스에서 **재현되지 않음** — 빌드·실행 모두 성공.

## 시도 1 — `--field stock=5` (잘못된 키, 침묵 무시)

```
$ .venv/bin/lnpl build <src> --run --workdir .claude/tmp/lnpl-build --field stock=5
# rc=0
step 1 validate order / step 2 find product → status completed  (create·update 스킵)
```

`stock=5`가 **조용히 무시**되고 가드 필드가 기본값 0으로 평가됨 → 2스텝만 실행.
경고·에러 없음(help의 "ignored" 동작이지만 진단 없음 — 침묵 실패).

## 시도 2 — `--field product.stock=5` (정답 키: 조건식의 점 표기 전체)

```
# rc=0
step 1 validate order → step 2 find product → step 3 create order → step 4 update product
status completed / exit=0
```

## S3 경계 — `--field product.stock=0`

```
# rc=0
step 1 validate order / step 2 find product → status completed  (가드 2개 스킵)
```

판정: PASS(빌드·실행). 가드 스킵 의미론은 mode A와 일치. `--field` 키는 가드
조건식의 점 표기 전체(`product.stock`)여야 하며, 오키는 침묵 무시된다.
