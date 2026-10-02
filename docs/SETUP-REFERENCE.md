# 설치·업데이트·재설치 참조

gatekit이 쓰는 프로그램(PowerShell 7, uv, Claude Code, Git, `.venv`)을 **사람이 직접
복사해서 실행**할 수 있게 모아 둔 문서입니다.

먼저 알아 둘 것:

- 보통은 채팅에 `/gatekit:setup`을 입력하면 됩니다. 점검만 하고, 설치는 채팅에서
  **허락한 항목만** 합니다. 이 문서는 그게 안 될 때, 또는 직접 하고 싶을 때 보세요.
- 아래 명령은 PowerShell(또는 터미널)에 붙여 넣어 실행합니다. 설치 뒤에는 Claude 앱
  (VS Code 창)을 **완전히 닫았다가 다시** 열어야 새 프로그램이 보입니다.
- 관리자 권한이 필요할 수 있는 것은 표에 적어 두었습니다. 회사 PC에서 막히면 아래
  "IT 담당자에게 보낼 문의문"을 쓰세요. 정책을 우회하지 마세요.

## 1. 관리 대상 프로그램

이 표는 `.claude/gatekit/scripts/packages.json`(단일 출처)과 같아야 하며, 테스트가
둘이 어긋나면 실패합니다.

| key | 이름 | winget ID | 수준 | 최소 버전 | 설치 형식 | 관리자 | 공식 스크립트 | 문서 |
|---|---|---|---|---|---|---|---|---|
| `pwsh` | PowerShell 7 | `Microsoft.PowerShell` | 필수 | 7.6.0 | msix | 예전 MSI 설치본이면 필요할 수 있음 | 없음 | https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows |
| `uv` | uv (Python 관리 도구) | `astral-sh.uv` | 필수 | 0.4.27 | - | 아니오 | https://astral.sh/uv/install.ps1 | https://docs.astral.sh/uv/getting-started/installation/ |
| `claude` | Claude Code (claude 명령) | `Anthropic.ClaudeCode` | 필수 | 2.1.277 | - | 아니오 | https://claude.ai/install.ps1 | https://code.claude.com/docs/en/setup |
| `git` | Git for Windows | `Git.Git` | 선택 | - | - | 필요할 수 있음 | 없음 | https://git-scm.com/download/win |

`.venv`(프로젝트 안의 Python 환경)는 프로그램이 아니라 폴더입니다. 5번을 보세요.
gatekit이 쓰는 Python은 **3.14 이상**이고, uv가 알아서 받습니다.

## 2. 도구별 명령

각 블록에서 **한 방법만** 고르면 됩니다. winget이 막혀 있으면 공식 스크립트를 쓰세요.

### 2-1. PowerShell 7 (`pwsh`, 필수)

| 하고 싶은 것 | 명령 |
|---|---|
| 설치 | `winget install --id Microsoft.PowerShell -e --source winget --installer-type msix` |
| 업데이트 | `winget upgrade --id Microsoft.PowerShell -e --installer-type msix` |
| 재설치 | `winget install --id Microsoft.PowerShell -e --installer-type msix --force` |
| 버전 확인 | `pwsh -NoProfile -Command $PSVersionTable.PSVersion.ToString()` |

- 공식 설치 스크립트 방식은 gatekit이 쓰지 않습니다(공식 문서의 설치 방법은 위 문서 링크).
- 관리자: MSIX 설치는 보통 필요 없습니다. **예전에 MSI로 설치한** PowerShell을 바꿀 때는
  Windows 관리자 확인 창(UAC)이 뜰 수 있습니다. 창이 뜨면 허용하거나 IT 담당자에게 문의하세요.
- 필수입니다. Claude Code가 명령을 실행할 때 쓰는 PowerShell 도구와 입력창의 `!` 명령이 PowerShell 7로 돌아갑니다
  (`.claude/settings.json`의 `env.CLAUDE_CODE_USE_POWERSHELL_TOOL = "1"`, `defaultShell = "powershell"`).
- winget이 없거나 막혀 있으면 Microsoft Store에서 "PowerShell"을 설치하세요. 둘 다 안 되면 IT 담당자에게 문의하세요.

### 2-2. uv (필수)

| 하고 싶은 것 | winget 방식 | 공식 스크립트 방식 |
|---|---|---|
| 설치 | `winget install --id astral-sh.uv -e` | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| 업데이트 | `winget upgrade --id astral-sh.uv -e` | `uv self update` |
| 재설치 | `winget install --id astral-sh.uv -e --force` | 설치 명령을 그대로 다시 실행 |
| 버전 확인 | `uv --version` | `uv --version` |

- 관리자 권한은 필요 없습니다(사용자 폴더에 설치).
- **`uv self update`가 실패하면**(`uv-receipt.json` 이 깨진 경우) 공식 스크립트 설치 명령을
  다시 실행하면 복구됩니다. setup은 이 경우 `-Update uv` 나 `-Reinstall uv` 로 같은 일을 합니다.
- 어떤 방법으로 설치했는지 모르겠으면 `/gatekit:setup` 표의 "설치 방법" 칸을 보세요.
  scoop이나 pip로 설치한 uv는 그 도구의 명령으로 바꾸세요(`scoop update uv`, `python -m pip install -U uv`).

### 2-3. Claude Code (`claude`, 필수)

| 하고 싶은 것 | 공식 스크립트 방식(권장) | winget 방식 |
|---|---|---|
| 설치 | `powershell -ExecutionPolicy ByPass -c "irm https://claude.ai/install.ps1 \| iex"` | `winget install --id Anthropic.ClaudeCode -e` |
| 업데이트 | `claude update` | `winget upgrade --id Anthropic.ClaudeCode -e` |
| 재설치 | 설치 명령을 그대로 다시 실행 | `winget install --id Anthropic.ClaudeCode -e --force` |
| 버전 확인 | `claude --version` | `claude --version` |

- 관리자 권한은 필요 없습니다.
- Claude 데스크톱 앱만으로는 `claude` 명령이 생기지 않습니다. 워커를 쓰려면 이 명령이 PATH 에 있어야 합니다.

### 2-3-1. 프로그램별 재설치를 setup 으로 하려면

`-Reinstall uv`, `-Reinstall pwsh`, `-Reinstall claude` 세 가지만 됩니다(허락한 항목만).
uv 는 설치 방법에 맞춰 winget `--force` 또는 공식 스크립트를 쓰고, pwsh 는 winget MSIX `--force`,
claude 는 공식 스크립트를 씁니다. 끝나면 버전을 다시 읽어 보여 줍니다.

### 2-4. Git for Windows (`git`, 선택)

| 하고 싶은 것 | 명령 |
|---|---|
| 설치 | `winget install --id Git.Git -e --source winget` (또는 https://git-scm.com/download/win) |
| 업데이트 | `winget upgrade --id Git.Git -e` |
| 버전 확인 | `git --version` |

- 관리자 권한이 필요할 수 있어 **gatekit은 자동으로 설치·업데이트·재설치하지 않고 명령만 알려 줍니다.**
- 없어도 gatekit은 동작합니다.

## 3. setup 스위치와 CLI 대응표

같은 일을 세 가지 방법으로 할 수 있습니다: 채팅(`/gatekit:setup`), 스크립트 직접 실행, CLI.

| 하고 싶은 것 | setup.ps1 스위치 | CLI (`gatekit.py setup ...`) |
|---|---|---|
| 점검만(아무것도 설치 안 함) | (없음) | (없음) |
| 프로그램 표·실패 기록만 보기 | `-Status` | `--status` |
| 설치 | `-Install pwsh,uv,claude,git,venv` | `--install X,Y` |
| 업데이트 | `-Update pwsh,uv,claude,git` | `--update X` |
| 재설치 | `-Reinstall uv,pwsh,claude` | `--reinstall X` |
| 지난 실패만 다시 시도 | `-RetryFailed` | `--retry-failed` |
| JSON 출력(ASCII) | `-Json` | `--json` |
| 출력 언어 | `-Lang ko` / `-Lang en` | `--lang ko` / `--lang en` |

- `venv` 는 `-Install venv` 로만 만듭니다(`-Update`, `-Reinstall` 에는 쓸 수 없음).
- 허용 목록 밖의 이름은 거부하고 종료 코드 1을 냅니다.

스크립트 직접 실행 형태(항상 이 플래그를 붙이세요):

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Reinstall uv -Lang ko
```

CLI 형태(프로젝트 폴더에서):

```
uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py setup --reinstall uv --lang ko
```

CLI는 위 스크립트를 그대로 부르고, 출력과 종료 코드도 그대로 돌려줍니다.

## 4. 종료 코드

| 코드 | 뜻 | 할 일 |
|---|---|---|
| 0 | 준비됨 | 없음 |
| 1 | 실패(허락으로 해결 안 되는 것: 잘못된 스위치, `.venv`를 못 만듦, 알 수 없는 설치 실패) | 출력의 마지막 줄을 읽고 원인을 고친 뒤 다시 실행 |
| 2 | 사용자의 허락·조치가 필요(필수 프로그램 없음, Python 받아야 함, 관리자 권한 필요 등) | 출력이 알려 주는 스위치를 허락하거나 직접 실행 |
| 3 | 설치는 됐지만 이 창에서는 안 보임(PATH), 또는 PC 재시작 필요 | Claude 앱(VS Code 창)을 완전히 닫고 다시 열기 |
| 4 | 회사·학교 정책이나 네트워크가 막음 | 아래 문의문을 IT 담당자에게 전달. 우회 금지 |

여러 문제가 섞이면 1 > 4 > 3 > 2 > 0 순서로 먼저 해당하는 코드가 나옵니다.

## 5. `.venv` (프로젝트 안 Python 환경)

| 하고 싶은 것 | 명령 |
|---|---|
| 만들기·재생성 | `powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install venv` |
| uv 로 직접 만들기 | `uv sync --project .claude/gatekit --frozen --no-dev` |
| 버전 확인 | `.claude/gatekit/.venv/Scripts/python.exe --version` (3.14 이상이어야 함) |

- Python 과 패키지를 **내려받습니다(수십 MB)**. 네트워크가 필요하고 몇 분 걸릴 수 있습니다.
- `-Install venv` 는 손상되었거나 3.14 보다 낮은 `.claude/gatekit/.venv` 폴더를 **지우고 다시 만듭니다**
  (프로젝트 안 폴더라 다시 만들 수 있습니다). 점검만 할 때는 아무것도 지우지 않습니다.
- 회사 프록시·인증서 환경이면 `UV_SYSTEM_CERTS=1`, `SSL_CERT_FILE`, `HTTPS_PROXY`,
  `UV_PYTHON_INSTALL_MIRROR` 를 확인하세요.

## 6. 자주 나오는 winget 오류 코드

| 코드 | 뜻 | setup 의 처리 | 할 일 |
|---|---|---|---|
| `0x8A15002B` | 업데이트할 것이 없음(이미 최신) | 성공으로 처리 | 없음 |
| `0x8A150061` | 이미 설치되어 있음 | 성공으로 처리 | 없음 |
| `0x8A15003A` | 정책이 winget 사용을 막음 | 종료 코드 4 (uv·claude 새 설치는 공식 스크립트로 자동 시도) | IT 담당자에게 문의 |
| `0x8A15010F` | 정책이 막음 | 종료 코드 4 | IT 담당자에게 문의 |
| `0x8A15001B` | 정책이 막음 | 종료 코드 4 | IT 담당자에게 문의 |
| `0x8A15001C` | 정책이 막음 | 종료 코드 4 | IT 담당자에게 문의 |
| `0x8A150109` | 설치는 끝났지만 PC 재시작 필요 | 종료 코드 3 | PC 를 다시 시작하고 setup 다시 실행 |
| `0x8A150107` | 설치 서버에 연결 못 함(네트워크) | 종료 코드 4 | 인터넷·VPN·프록시 확인 후 재시도 |
| `0x80072EFD` | 보안 연결(TLS)·서버 연결 실패 | 종료 코드 4 | 집 네트워크나 핫스팟에서 재시도 |
| `0x8A150046` | winget 소스 약관에 아직 동의 안 함 | 종료 코드 2 | 터미널에서 `winget search git` 을 한 번 실행해 직접 동의하거나, 설치를 다시 허락 |
| `0x8A150041` | winget 소스 약관에 아직 동의 안 함 | 종료 코드 2 | 위와 같음 |

위에 없는 코드는 "알 수 없는 오류"(종료 코드 1)로 처리하고 출력의 마지막 줄을 보여 줍니다.

## 7. 실패 기록과 다시 시도

설치·업데이트·재설치가 실패하면 `.gatekit/runs/setup-last.json` 에 시각, 항목, 동작,
종료 코드, 분류, 메시지가 남습니다. 같은 항목이 나중에 성공하면 그 기록은 지워집니다.

- 기록 보기: `-Status`(또는 점검 출력의 "지난 실패 기록" 줄)
- 다시 시도: `-RetryFailed` — 기록된 항목만, **같은 동작**으로 다시 합니다. 채팅에서는
  다시 시도하기 전에 허락을 한 번 더 묻습니다. 기록이 없으면 안내 한 줄만 나옵니다.

## 8. IT 담당자에게 보낼 문의문 예시

setup 이 막힘을 알릴 때 같은 내용을 자동으로 만들어 줍니다. 직접 쓸 때는 이 예시를 쓰세요.

> IT 담당자님, 제 PC(Windows)에서 uv 설치가 오류 0x8A15003A 로 실패했습니다.
> 조직 정책(AppLocker/Intune)이나 프록시·방화벽이 winget, astral.sh, claude.ai 접속을
> 막고 있는지 확인하고, 사용자 권한으로 허용해 주실 수 있나요?

## 9. CLI가 안 될 때: 스크립트를 직접 실행

CLI(`gatekit.py`)는 uv 와 `.venv` 가 있어야 시작됩니다. uv 가 깨졌거나 `.venv` 가 없을 때는
CLI를 부를 수 없으니 **스크립트를 직접** 실행하세요. 스크립트는 Windows 에 기본으로 있는
Windows PowerShell 5.1 만 있으면 됩니다.

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Lang ko
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Reinstall uv -Lang ko
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install venv -Lang ko
```

이 스크립트도 안 돌면(파일이 없음 등) 저장소에서 복원하세요: `git checkout .claude/gatekit/scripts`.
