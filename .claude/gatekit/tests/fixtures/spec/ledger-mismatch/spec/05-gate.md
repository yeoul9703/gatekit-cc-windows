# 메모 앱 — 완료 게이트

## 완료 기준

```gatekit-criterion
{"id": "note-store-tests", "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0}, "timeout_s": 30}
```

```gatekit-criterion
{"id": "note-ui-tests", "argv": ["python3", "-m", "unittest", "discover"],
 "expect": {"exit": 0}, "timeout_s": 30}
```

## 완료로 보지 않는 조건

- 테스트를 건너뛰어 통과시킨 경우
- 시간 초과로 판정하지 못한 경우

## 증거 수집 방법

| 기준 | 실행 방법 | 남는 증거 |
|---|---|---|
| note-store-tests | contract run | 종료 코드 |
