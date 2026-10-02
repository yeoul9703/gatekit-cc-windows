---
title: "{{project_name}} — 완료 게이트"
date: "{{date}}"
status: "초안"
---

# {{project_name}} — 완료 게이트

이 파일은 "끝났다"의 정의다. 사람이 승인하면 해시가 고정되고, Stop 훅이
여기 적힌 명령을 실제로 실행해 판정한다. 말로 하는 완료 선언은 근거가 아니다.

## 완료 기준

각 기준은 `gatekit-criterion` 블록 하나다. `argv`는 셸 없이 실행되며,
`cwd`는 프로젝트 루트다. `id`에 대응하는 작업 id를 포함시켜 추적성을 유지한다.

```gatekit-criterion
{"id": "tests-pass",
 "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0},
 "timeout_s": 30}
```

```gatekit-criterion
{"id": "task-one-works",
 "argv": ["{{실행 가능한 검증 명령}}"],
 "expect": {"exit": 0},
 "timeout_s": 30,
 "artifacts": ["{{reports/task-one.txt}}"]}
```

필드 규칙:

| 필드 | 규칙 |
|---|---|
| `id` | 고유. 04의 작업 id를 참조하면 추적성 경고가 사라진다. |
| `argv` | 비어 있지 않은 문자열 리스트. 셸 문법(`&&`, 파이프)은 쓸 수 없다. |
| `expect.exit` | 통과로 볼 종료 코드. 보통 0. |
| `timeout_s` | 이 기준의 상한. 전체 예산은 기본 45초이며 아래 `gatekit-budget` 펜스로 최대 600초까지 올릴 수 있다. |
| `artifacts` | 실행 후 존재해야 하는 상대 경로. 없으면 `fail`. |

## 완료로 보지 않는 조건

아래에 해당하면 통과가 아니다. 하나라도 걸리면 `fail` 또는 `unverified`다.

- 테스트를 건너뛰거나(`skip`, `only`) 비활성화해서 통과시킨 경우
- 기준 명령이 시간 초과된 경우 — `unverified`이며 통과로 반올림하지 않는다
- 산출물 파일이 없는데 명령만 0으로 끝난 경우
- 구현 없이 TODO·스텁·빈 함수만 남긴 경우
- `05-gate.md`를 고쳐서 실패하는 기준을 삭제한 경우 — 승인 해시가 깨져
  `contract_stale`로 잡힌다
- 사람이 직접 실행해보지 않은 채 "동작한다"고 보고한 경우

## 증거 수집 방법

| 기준 | 실행 방법 | 남는 증거 |
|---|---|---|
| tests-pass | `python3 -m gatekit contract run` | 종료 코드, stdout 꼬리 |
| {{task-one-works}} | {{}} | {{산출물 파일의 sha256}} |

승인 절차: 이 문서를 사람이 읽고 동의하면 `python3 -m gatekit approve spec/05-gate.md`
를 실행한다. 이후 문서가 바뀌면 승인이 만료되고 다시 승인해야 한다.

## 실행 예산 (선택)

기준을 모두 합친 실행이 45초를 넘는다면 예산을 선언한다. 선언하지 않으면 45초다.
느리지만 정직하게 통과하는 스위트가 예산에 잘려 영원히 `unverified`가 되는 것을 막는다.

```gatekit-budget
{"total_budget_s": 180}
```

상한은 600초다. 그보다 오래 걸리는 검사는 정지 게이트가 아니라 빌드 단계에 두어야 한다.
