---
title: "{{project_name}} — 작업 목록"
date: "{{date}}"
status: "초안"
---

# {{project_name}} — 작업 목록

각 작업은 아래 형식의 `gatekit-task` 블록 하나로 표현한다. `jobs.py`가 이
블록을 읽어 워커에 넘기고, 쓰기 게이트가 `write_scope`를 강제한다.

## 작업 목록

작업은 수직 슬라이스로 자른다. 화면·로직·데이터가 함께 도는 단위여야 하고,
"모델만 만드는 작업" 같은 수평 레이어는 만들지 않는다.

```gatekit-task
{"id": "task-one",
 "title": "{{한 줄 제목}}",
 "write_scope": ["{{src/feature-a/**}}"],
 "instruction": "{{이 작업만 보고도 끝낼 수 있는 자기완결 지시. 무엇을 만들고, 어떤 파일에 쓰고, 무엇이 되면 끝인지.}}",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": [],
 "round": 1}
```

```gatekit-task
{"id": "task-two",
 "title": "{{한 줄 제목}}",
 "write_scope": ["{{src/feature-b/**}}"],
 "instruction": "{{…}}",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": ["task-one"],
 "round": 2}
```

필드 규칙:

| 필드 | 규칙 |
|---|---|
| `id` | 전체에서 고유. 완료 기준(05)이 이 id를 참조한다. |
| `write_scope` | 비어 있지 않은 글롭 목록, 또는 조사만 하는 작업이면 문자열 `"read-only"`. |
| `instruction` | 자기완결. 다른 문서를 읽지 않아도 수행 가능해야 한다. |
| `gates` | 최소 1개. 셸 없이 실행되는 argv 리스트. 종료 코드 0은 `ok`, 3은 `unverified`(돌긴 했으나 판정할 수 없었음), 그 밖의 0이 아닌 값은 `fail`. |
| `depends_on` | 이 파일 안에 존재하는 id만. |
| `round` | 같은 라운드의 작업은 병렬로 돈다. |

## 실행 순서

| 라운드 | 작업 | 병렬 가능 이유 |
|---|---|---|
| 1 | task-one | {{다른 작업과 파일이 겹치지 않음}} |
| 2 | task-two | {{task-one의 산출물에 의존}} |

## 범위 규칙

- 같은 라운드의 두 작업은 `write_scope`가 겹칠 수 없다. 겹치면
  `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate`가 `fail`을 낸다.
- 워커는 자기 `write_scope` 밖을 쓸 수 없다. 쓰기 게이트가 막는다.
- 범위를 넓혀야 하면 워커가 임의로 넓히지 말고 작업을 다시 나눈다.
