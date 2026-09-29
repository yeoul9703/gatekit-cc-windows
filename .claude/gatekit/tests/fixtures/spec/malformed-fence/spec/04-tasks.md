# 메모 앱 — 작업 목록

## 작업 목록

```gatekit-task
{"id": "note-store", "title": "메모 저장소", "write_scope": ["src/store/**"],
 "instruction": "메모를 파일에 저장하고 읽는 함수를 만든다.",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": [], "round": 1,}
```

```gatekit-task
{"id": "note-ui", "title": "메모 목록 화면", "write_scope": ["src/ui/**"],
 "instruction": "저장소를 읽어 목록을 그린다.",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}],
 "depends_on": ["note-store"], "round": 2}
```

## 실행 순서

| 라운드 | 작업 | 병렬 가능 이유 |
|---|---|---|
| 1 | note-store | 겹치는 파일 없음 |
| 2 | note-ui | note-store에 의존 |

## 범위 규칙

- 같은 라운드의 작업은 write_scope가 겹칠 수 없다.
