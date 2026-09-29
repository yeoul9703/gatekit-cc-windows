# gpters-24th-gate-kit

**Windows + Claude Code 전용 gatekit.** 원래 Claude Code 플러그인이던
[gatekit](https://github.com/LovelyPaul/gatekit)을, 폴더만 열면 동작하는
독립 구성(`.claude/`)으로 바꾼 fork입니다. 기획(interview)부터 완료 기준(gate),
작업 실행(build), 독립 검증(verify)까지를 훅으로 강제합니다. 필요한 프로그램은
Claude Code와 uv뿐이며, Python은 uv가 준비하고 코드는 표준 라이브러리만 씁니다.

- 사용법 (처음 쓰는 분): [docs/USAGE.md](docs/USAGE.md)
- 설계 (개발자): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 결정 기록: [docs/decisions/ADR-0018-windows-standalone-uv.md](docs/decisions/ADR-0018-windows-standalone-uv.md)
