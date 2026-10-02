---
title: "{{project_name}} — 작업 목록"
date: "{{date}}"
status: "초안"
---

# {{project_name}} — 작업 목록

각 작업은 아래 형식의 `gatekit-task` 블록 하나로 표현한다. build가 이
블록을 읽어 작업마다 안내문을 만든다. 만드는 일은 하위 에이전트가 그
안내문을 읽고 하며(라운드에 작업이 하나뿐이면 메인 세션이 직접 한다),
통과는 그 작업의 `gates`가 판정한다.

## 작업 목록

작업은 수직 슬라이스로 자른다. 화면·로직·데이터가 함께 도는 단위여야 하고,
"모델만 만드는 작업" 같은 수평 레이어는 만들지 않는다.

```gatekit-task
{"id": "task-one",
 "title": "{{한 줄 제목}}",
 "write_scope": ["{{src/feature-a/**}}"],
 "instruction": "{{이 작업만 보고도 끝낼 수 있는 자기완결 지시. 무엇을 만들고, 어떤 파일에 쓰고, 무엇이 되면 끝인지.}}",
 "read": ["spec/01-prd.md", "spec/03-architecture.md"],
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": [],
 "round": 1}
```

```gatekit-task
{"id": "task-two",
 "title": "{{한 줄 제목}}",
 "write_scope": ["{{src/feature-b/**}}"],
 "instruction": "{{…}}",
 "read": ["spec/02-screens.md", "{{src/feature-a/따라야 할 파일}}"],
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": ["task-one"],
 "round": 2}
```

필드 규칙:

| 필드 | 규칙 |
|---|---|
| `id` | 전체에서 고유. 완료 기준(05)이 이 id를 참조한다. |
| `write_scope` | 비어 있지 않은 글롭 목록, 또는 조사만 하는 작업이면 문자열 `"read-only"`. |
| `instruction` | 자기완결. `read`에 적은 파일 말고는 다른 문서를 읽지 않아도 수행 가능해야 한다. |
| `read` | 없어도 된다. 이 작업을 만들기 전에 읽을 파일의 목록: 스펙의 해당 문서, 손댈 코드, 따라야 할 기존 코드. 프로젝트 루트 기준 상대 경로로 적는다 (`@`, 절대 경로, `..`, 역슬래시는 쓰지 않는다). 앞 작업이 만들 파일을 적어도 된다. |
| `gates` | 최소 1개. 셸 없이 실행되는 argv 리스트. 종료 코드 0은 `ok`, 3은 `unverified`(돌긴 했으나 판정할 수 없었음), 그 밖의 0이 아닌 값은 `fail`. |
| `depends_on` | 이 파일 안에 존재하는 id만. 앞 작업이 쓴 경로(`write_scope`)는 안내문에 자동으로 실린다. |
| `round` | 같은 라운드에 작업이 둘 이상이면 하위 에이전트에 하나씩 맡겨 함께 돌리고, 하나뿐이면 메인 세션이 직접 한다. |

## 실행 순서

| 라운드 | 작업 | 병렬 가능 이유 |
|---|---|---|
| 1 | task-one | {{다른 작업과 파일이 겹치지 않음}} |
| 2 | task-two | {{task-one의 산출물에 의존}} |

## 범위 규칙

- 같은 라운드의 두 작업은 `write_scope`가 겹칠 수 없다. 겹치면
  `uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py spec validate`가 `fail`을 낸다.
- 작업을 구현할 때 그 작업의 `write_scope` 밖은 고치지 않는다.
- 작업을 하위 에이전트에 나눠 맡길 때 같은 때 도는 둘의 범위가 겹치면 위임이 막힌다.
- 범위를 넓혀야 하면 임의로 넓히지 말고 작업을 다시 나눈다.
