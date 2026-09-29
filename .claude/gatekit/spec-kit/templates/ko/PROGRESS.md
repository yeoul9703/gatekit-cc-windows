---
title: "{{project_name}} — 진행 상황"
date: "{{date}}"
status: "{{not-started | in-progress | blocked | done}}"
---

# {{project_name}} — 진행 상황

기계와 사람이 함께 읽는 파일이다. 아래 본문 첫 줄의 `STATUS:` 형식을 바꾸지
않는다 — frontmatter의 `status`는 사람이 파일을 열지 않고도 알 수 있게 요약한
것일 뿐, 본문의 `STATUS:` 줄이 기준이다.

STATUS: {{not-started | in-progress | blocked | done}} · {{iso 타임스탬프}}

## 현재 상태

지금 무엇이 되고 무엇이 안 되는지 한 문단. 계획이 아니라 관측값을 쓴다.

| 항목 | 값 |
|---|---|
| 진행 중인 파이프라인 | {{interview / mockup / tasks / gate / build / verify}} |
| 통과한 완료 기준 | {{n}} / {{총 개수}} |
| 마지막 판정 | {{ok / warn / fail / unverified}} |
| 열린 가정 | {{n}}건 |

## 마일스톤

| 마일스톤 | 상태 | 타임스탬프 | 증거 |
|---|---|---|---|
| 스펙 승인 | {{완료/미완료}} | {{iso}} | `gatekit approve check spec/05-gate.md` |
| {{task-one}} | {{}} | {{iso}} | {{게이트 이름과 종료 코드}} |

타임스탬프는 "어제", "방금" 같은 상대 표현이 아니라 ISO 8601로 적는다.

## 실패한 시도

무엇을 해봤고 왜 실패했는지 남긴다. 이 표가 비어 있는데 재시도가 있었다면
기록이 누락된 것이다.

| # | 시도 | 결과 | 원인 | 다음에 하지 말 것 |
|---|---|---|---|---|
| 1 | {{무엇을 시도했는가}} | {{fail / unverified}} | {{관측된 원인}} | {{같은 방법을 반복하지 않기}} |

## 마지막 검증

| 항목 | 값 |
|---|---|
| 실행 명령 | `python3 -m gatekit contract run --json` |
| 실행 시각 | {{iso}} |
| 판정 | {{ok / warn / fail / unverified}} |
| 실패·미검증 기준 | {{id 목록, 없으면 "없음"}} |
| 증거 위치 | {{.gatekit/runs/ 또는 산출물 경로}} |

`unverified`는 실패가 아니지만 통과도 아니다. 무엇을 확인하지 못했는지
그대로 적고, 통과 쪽으로 반올림하지 않는다.
