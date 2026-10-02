# 설치·업데이트·재설치 참조

gatekit이 쓰는 프로그램(winget, PowerShell 7, uv, Claude Code, Git, `.venv`)을 **사람이 직접
복사해서 실행**할 수 있게 모아 둔 문서입니다.

먼저 알아 둘 것:

- 보통은 채팅에 `/gatekit-setup`을 입력하면 됩니다. 점검만 하고, 설치는 채팅에서
  **허락한 항목만** 합니다. 이 문서는 그게 안 될 때, 또는 직접 하고 싶을 때 보세요.
- 아래 명령은 PowerShell(또는 터미널)에 붙여 넣어 실행합니다. 설치 뒤에는 Claude Code
  (데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 **완전히 닫았다가 다시** 열어야 새 프로그램이 보입니다.
  데스크톱 앱은 창을 닫아도 남아 있으니 작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료하세요.
- 관리자 권한이 필요할 수 있는 것은 표에 적어 두었습니다. 회사 PC에서 막히면 아래
  "IT 담당자에게 보낼 문의문"을 쓰세요. 정책을 우회하지 마세요.

## 1. 관리 대상 프로그램

이 표는 `.claude/gatekit/scripts/packages.json`(단일 출처)과 같아야 하며, 테스트가
둘이 어긋나면 실패합니다.

| key | 이름 | winget ID | 수준 | 최소 버전 | 설치 형식 | 관리자 | 공식 스크립트 | 문서 |
|---|---|---|---|---|---|---|---|---|
| `winget` | winget (앱 설치 관리자) | `Microsoft.AppInstaller` | 권장 | - | - | 아니오 | 없음 | https://learn.microsoft.com/windows/package-manager/winget/ |
| `pwsh` | PowerShell 7 | `Microsoft.PowerShell` | 필수 | 7.6.0 | msix | 예전 MSI 설치본이면 필요할 수 있음 | 없음 | https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows |
| `uv` | uv (Python 관리 도구) | `astral-sh.uv` | 필수 | 0.4.27 | - | 아니오 | https://astral.sh/uv/install.ps1 | https://docs.astral.sh/uv/getting-started/installation/ |
| `claude` | Claude Code (claude 명령) | `Anthropic.ClaudeCode` | 권장 | 2.1.277 | - | 아니오 | https://claude.ai/install.ps1 | https://code.claude.com/docs/en/setup |
| `git` | Git for Windows | `Git.Git` | 권장 | - | - | 사용자 범위 설치가 안 될 때만 필요할 수 있음 | 없음 | https://git-scm.com/download/win |

`.venv`(프로젝트 안의 Python 환경)는 프로그램이 아니라 폴더입니다. 5번을 보세요.
gatekit이 쓰는 Python은 **3.14 이상**이고, uv가 알아서 받습니다.

`packages.json`에는 표에 없는 값이 세 가지 더 있습니다. `appx_name`·`appx_preview_name`은
Windows 패키지 이름(안정판과 preview를 구분할 때 씀), `store_url`은 Microsoft Store 주소입니다.

## 2. 도구별 명령

각 블록에서 **한 방법만** 고르면 됩니다. winget이 막혀 있으면 공식 스크립트를 쓰세요.

### 2-0. winget (권장)

winget은 Windows의 "앱 설치 관리자(App Installer)"에 들어 있고 Microsoft Store가 배포합니다.
Windows 11에는 보통 이미 있습니다. 없을 때 `-Install winget`이 하는 일은 아래 순서입니다.
앞 단계에서 winget이 보이면 거기서 멈춥니다.

| 순서 | 하는 일 | 직접 하려면 | 내려받기 | 관리자 |
|---|---|---|---|---|
| 1 | PC에 이미 있는 앱 설치 관리자를 Windows에 등록해 달라고 요청 | `Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe` | 없음 | 아니오 |
| 2 | PowerShell Gallery에서 `Microsoft.WinGet.Client` 모듈을 사용자 폴더에 받아 winget을 복구 | 아래 세 줄 | 있음(모듈과 앱 설치 관리자) | 아니오 |
| 3 | 그래도 없으면 Microsoft Store 주소를 알려 주고 종료 코드 2 | https://apps.microsoft.com/detail/9nblggh4nns1 에서 "앱 설치 관리자" 설치 | - | - |

2단계를 직접 할 때(Windows PowerShell에서):

```
Install-PackageProvider -Name NuGet -Scope CurrentUser -Force
Install-Module -Name Microsoft.WinGet.Client -Scope CurrentUser -Force -Repository PSGallery
Repair-WinGetPackageManager
```

| 하고 싶은 것 | 명령 |
|---|---|
| 업데이트 | `winget upgrade --id Microsoft.AppInstaller -e` (보통은 Microsoft Store가 알아서 업데이트합니다) |
| 버전 확인 | `winget --version` |

- 관리자 권한은 필요 없습니다. 두 명령 모두 `-Scope CurrentUser`로 사용자 폴더에만 설치하고,
  `Repair-WinGetPackageManager`는 `-AllUsers`를 붙일 때만 관리자 권한이 필요합니다(gatekit은 붙이지 않습니다).
- 회사·학교 정책이나 네트워크가 막으면 종료 코드 4가 나옵니다. IT 담당자에게 문의하세요.
- `-Update winget`, `-Reinstall winget`은 없습니다(거부, 종료 코드 1).
- PowerShell 7도 없을 때는 점검 결과가 `-Install winget,pwsh`를 알려 줍니다. 순서를 어떻게 적어도
  winget을 먼저 설치합니다.
- uv와 Claude Code는 winget 없이도(공식 스크립트로) 설치됩니다.
- `-Install winget,pwsh`에서 winget 설치가 실패하면 PowerShell 7 줄(`S16-pwsh`)은
  "winget 설치가 실패해서 PowerShell 7 을(를) 설치하지 못했습니다"라고 원인을 알려 줍니다.
  먼저 winget 줄(`S16-winget`)의 안내를 해결하세요.

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
  이 두 값이 빠지면 setup(`S12-settings`)과 doctor(훅 등록 축)가 둘 다 실패로 알려 줍니다.
- winget이 없으면 `-Install winget,pwsh`로 함께 설치합니다(2-0). winget이 막혀 있으면 Microsoft Store에서
  "PowerShell"을 설치하세요. 둘 다 안 되면 IT 담당자에게 문의하세요.

#### 안정판인지 판정하는 방법

setup은 PATH에서 어느 `pwsh`가 먼저 잡히는지가 아니라 **안정판 제품이 설치돼 있는지**를 봅니다.
preview는 안정판과 다른 제품이라 preview만 있으면 설치된 것으로 치지 않습니다.

| | 안정판 | preview |
|---|---|---|
| winget ID | `Microsoft.PowerShell` | `Microsoft.PowerShell.Preview` |
| Windows 패키지 이름 (`Get-AppxPackage -Name`) | `Microsoft.PowerShell` | `Microsoft.PowerShellPreview` |
| MSI 설치 폴더 | `Program Files\PowerShell\7\` | `Program Files\PowerShell\7-preview\` |

찾는 순서는 Windows 패키지 → MSI 설치 폴더 → PATH에 있는 `pwsh`의 버전 문자열(`-preview` 같은
접미사가 없으면 안정판)입니다. 패키지 조회는 winget 없이, Windows에 기본으로 있는
Windows PowerShell 5.1에서 됩니다.

| 상태 | 판정(`S2`) | 알려 주는 것 |
|---|---|---|
| 안정판이 있고 7.6.0 이상 | `ok`. PATH에서 preview가 먼저 잡히면 그 사실만 덧붙임 | 없음 |
| 안정판이 있지만 7.6.0 미만 | `fail` | `-Update pwsh` |
| preview만 있음 | `fail` | `-Install pwsh` |
| 아무것도 없음 | `fail` | `-Install pwsh` (winget도 없으면 `-Install winget,pwsh`) |
| 안정판이 설치돼 있지만 이 창의 PATH에 `pwsh`가 없음 | `warn`, 종료 코드 3 | Claude Code를 완전히 닫고 다시 열기 |

더 새 안정판이 나왔는지는 패키지 표의 `pwsh` 줄이 winget 조회로 알려 줍니다(경고).

세션을 시작할 때 도는 짧은 점검(`session-check.ps1`)도 같은 규칙을 씁니다(판정 함수는
`common.ps1` 한 곳에 있습니다). 다만 `pwsh`를 실행해 보지는 않고 Windows 패키지, MSI 설치 폴더,
PATH에 있는 `pwsh.exe` 파일에 적힌 버전만 봅니다. preview만 있으면 "미리보기(preview) 버전만
있고 안정판이 없습니다"라고 알려 주고, 어느 쪽인지 알 수 없으면 아무 말도 하지 않습니다.

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
- 어떤 방법으로 설치했는지 모르겠으면 `/gatekit-setup` 표의 "설치 방법" 칸을 보세요.
  scoop이나 pip로 설치한 uv는 그 도구의 명령으로 바꾸세요(`scoop update uv`, `python -m pip install -U uv`).

### 2-3. Claude Code (`claude` 명령, 권장)

Claude Code 자체는 필요합니다. 데스크톱 앱, VS Code 확장, 터미널 중 어느 것이든 됩니다.
여기서 다루는 것은 터미널에서 쓰는 `claude` 명령(CLI)이고, 이것은 **권장**입니다.
기본 설정에서는 gatekit이 이 명령을 실행하는 곳이 없습니다. build는 지금 세션이 직접
작업하고(`build.execution`의 기본값 `host`), verify의 검토는 세션의 읽기 전용
서브에이전트가 합니다.

`claude` 명령이 필요한 것은 프로젝트의 `.gatekit/config.json`이 아래 둘 중 하나일 때뿐입니다.

- `build.execution`이 `"worker"` (build를 워커 방식으로 돌림)
- `verify.evaluator`에 `agent`가 아닌 백엔드 이름을 적음

setup(`S6`)은 이 설정을 읽어 이렇게 판정합니다. 설정 파일이 없거나 읽을 수 없으면 기본으로 봅니다.

| 상태 | 기본 설정 | `claude` 명령이 필요한 프로젝트 |
|---|---|---|
| 이 창의 PATH에 없음 | `warn`(권장), 종료 코드에 영향 없음 | `fail`(필수), 종료 코드 2, `-Install claude` |
| 설치돼 있지만 이 창의 PATH에 안 보임 | `warn`, 종료 코드에 영향 없음 | `warn`, 종료 코드 3 |
| 권장 버전(2.1.277)보다 낮음 | `warn`, 종료 코드에 영향 없음, `-Update claude` | `warn`, 종료 코드에 영향 없음, `-Update claude` |

세션 시작 점검(`session-check.ps1`)도 같은 규칙을 씁니다. 기본 설정에서는 `claude` 명령이
없어도 아무 말도 하지 않고, 필요한 프로젝트에서만 알립니다. `/gatekit-doctor`의 워커 항목도
기본 설정에서는 통과(`ok`)이고 "지금 설정에서는 쓰지 않는다"고 적습니다.

설치하고 싶을 때의 명령은 아래와 같습니다.

| 하고 싶은 것 | 공식 스크립트 방식(권장) | winget 방식 |
|---|---|---|
| 설치 | `powershell -ExecutionPolicy ByPass -c "irm https://claude.ai/install.ps1 \| iex"` | `winget install --id Anthropic.ClaudeCode -e` |
| 업데이트 | `claude update` | `winget upgrade --id Anthropic.ClaudeCode -e` |
| 재설치 | 설치 명령을 그대로 다시 실행 | `winget install --id Anthropic.ClaudeCode -e --force` |
| 버전 확인 | `claude --version` | `claude --version` |

- 관리자 권한은 필요 없습니다.
- 데스크톱 앱이나 VS Code 확장을 설치해도 `claude` 명령은 생기지 않습니다. build를 워커 방식으로 돌릴 때만 위 명령으로 따로 설치하세요.

### 2-3-1. 프로그램별 재설치를 setup 으로 하려면

`-Reinstall uv`, `-Reinstall pwsh`, `-Reinstall claude` 세 가지만 됩니다(허락한 항목만).
uv 는 설치 방법에 맞춰 winget `--force` 또는 공식 스크립트를 쓰고, pwsh 는 winget MSIX `--force`,
claude 는 공식 스크립트를 씁니다. 끝나면 버전을 다시 읽어 보여 줍니다.

### 2-4. Git for Windows (`git`, 권장)

없어도 gatekit은 동작합니다. 권장하는 이유는 되돌릴 방법이 생기기 때문입니다. Git이 없으면
저장소를 압축 파일로 받게 되는데, 그러면 빠지거나 망가진 파일을 `git checkout`으로 되돌릴 수 없고
(9번) 작업 이력도 남지 않습니다.

| 하고 싶은 것 | 명령 |
|---|---|
| 설치 | `winget install --id Git.Git -e --source winget --scope user` |
| 사용자 범위 설치가 안 될 때 | `winget install --id Git.Git -e --source winget` (또는 https://git-scm.com/download/win 에서 설치 파일 받기) |
| 업데이트 | `winget upgrade --id Git.Git -e` |
| 버전 확인 | `git --version` |

setup(`S7`)은 이렇게 판정합니다. 권장 항목이라 어느 경우에도 종료 코드를 바꾸지 않습니다.

| 상태 | 판정(`S7`) | 알려 주는 것 |
|---|---|---|
| 이 창의 PATH에 있음 | `ok` | 없음 |
| 없음 | `warn`(권장), 종료 코드에 영향 없음 | `-Install git` (winget도 없으면 `-Install winget,git`) |
| 설치돼 있지만 이 창의 PATH에 안 보임 | `warn`, 종료 코드에 영향 없음 | Claude Code를 완전히 닫고 다시 열기 |

`-Install git`은 채팅에서 허락한 뒤에만 실행하고, 아래 순서로 합니다.

| 순서 | 하는 일 | 관리자 |
|---|---|---|
| 1 | 사용자 범위로 설치(`--scope user`) | 아니오 |
| 2 | 1이 안 되면 "관리자 확인 창(UAC)이 뜰 수 있고 다른 창 뒤에 숨을 수 있다"고 먼저 알린 뒤(`S10-git`) 범위 없이 한 번 더 설치 | 필요할 수 있음 |
| 3 | 그래도 안 되면 실패로 알리고(`S16-git`, 표(6번)에 없는 오류면 종료 코드 1) 직접 설치할 주소를 보여 줌 | - |

- 2번으로 넘어가는 것은 1번이 표(6번)에 없는 오류로 끝났을 때뿐입니다. 정책 차단, 네트워크 문제, 약관 미동의,
  제한 시간 초과는 범위를 바꿔도 달라지지 않으므로 다시 시도하지 않고 그 오류의 종료 코드(4 또는 2)로 끝냅니다.
- 관리자 확인 창은 winget과 Git 설치 프로그램이 직접 띄웁니다. setup은 스스로 관리자 권한을 얻으려 하지 않습니다.
  창이 보이지 않으면 작업 표시줄에서 깜박이는 아이콘을 눌러 보세요. 답하지 않으면 15분 뒤에 중단합니다(종료 코드 4).
- gsudo 같은 권한 상승 도구는 쓰지 않습니다. gsudo도 같은 관리자 확인 창을 띄울 뿐이고, 관리자 권한이 없는
  계정에서는 어느 쪽도 넘지 못합니다. 설치할 프로그램만 하나 늘어납니다.
- 사용자 범위 설치가 관리자 확인 창 없이 끝나는지는 Git이 없는 PC에서 아직 확인하지 못했습니다.
  winget이 `--scope user`에 맞는 설치 프로그램을 고르는 것까지만 확인했습니다(2026-10-02).
- 이미 있는 Git은 setup이 업데이트하거나 다시 설치하지 않습니다(`-Update git`은 알림만, `-Reinstall git`은 거부).
  위 명령으로 직접 하세요.

## 3. setup 스위치와 CLI 대응표

같은 일을 세 가지 방법으로 할 수 있습니다: 채팅(`/gatekit-setup`), 스크립트 직접 실행, CLI.

| 하고 싶은 것 | setup.ps1 스위치 | CLI (`gatekit.py setup ...`) |
|---|---|---|
| 점검만(아무것도 설치 안 함) | (없음) | (없음) |
| 프로그램 표·실패 기록만 보기 | `-Status` | `--status` |
| 설치 | `-Install winget,pwsh,uv,claude,git,venv` | `--install X,Y` |
| 업데이트 | `-Update pwsh,uv,claude,git` | `--update X` |
| 재설치 | `-Reinstall uv,pwsh,claude` | `--reinstall X` |
| 지난 실패만 다시 시도 | `-RetryFailed` | `--retry-failed` |
| JSON 출력(ASCII) | `-Json` | `--json` |
| 출력 언어 | `-Lang ko` / `-Lang en` | `--lang ko` / `--lang en` |

- `venv` 는 `-Install venv` 로만 만듭니다(`-Update`, `-Reinstall` 에는 쓸 수 없음).
- `winget` 도 `-Install winget` 만 됩니다(2-0). `-Install` 목록에 있으면 항상 가장 먼저 처리합니다.
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
| 2 | 사용자의 허락·조치가 필요(필수 프로그램 없음, Python 받아야 함 등) | 출력이 알려 주는 스위치를 허락하거나 직접 실행 |
| 3 | 설치는 됐지만 이 창에서는 안 보임(PATH), 또는 PC 재시작 필요 | Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 열기. 데스크톱 앱은 창을 닫아도 남아 있으니 작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료 |
| 4 | 회사·학교 정책이나 네트워크가 막음(winget 정책, 네트워크, 그룹 정책이 고정한 실행 정책, 프로그램 실행 차단) | 아래 문의문을 IT 담당자에게 전달. 우회 금지 |

여러 문제가 섞이면 1 > 4 > 3 > 2 > 0 순서로 먼저 해당하는 코드가 나옵니다.

`claude` 명령은 권장 항목이라 기본 설정에서는 없거나, 이 창에서 안 보이거나, 버전이 낮아도
종료 코드가 바뀌지 않습니다. 다른 필수 항목이 모두 준비돼 있으면 0입니다. `claude` 명령이
필요한 프로젝트(2-3 참고)에서만 없을 때 2, 이 창에서 안 보일 때 3이 됩니다.

Git도 권장 항목이라 없거나 이 창에서 안 보여도 종료 코드가 바뀌지 않습니다. 허락받은
`-Install git`이 실패했을 때만 그 실패의 종료 코드가 나옵니다(2-4 참고).

종료 코드 3에서 "완전히 닫는다"는 것은 프로그램을 끝내는 것입니다. Claude 데스크톱 앱은 창의 X를 눌러도
끝나지 않고 작업 표시줄 오른쪽 아래(트레이)에 남습니다. 남아 있는 앱은 시작할 때의 PATH를 그대로 쓰기 때문에
창만 닫았다 열면 새 프로그램이 여전히 보이지 않습니다. 트레이의 Claude 아이콘에서 종료한 뒤 다시 여세요.
아이콘이 안 보이면 트레이의 `^`를 눌러 숨은 아이콘을 펼치세요.

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
- `.venv` 에는 개발용 도구(pyright, ruff)를 넣지 않습니다. `pyproject.toml` 의 `[tool.uv]` 에
  `default-groups = []` 가 있어서 `uv run --frozen ...` 으로 명령을 실행해도 받지 않습니다.
  개발자가 `scripts/verify.ps1` 을 돌릴 때만 `--group dev` 로 받습니다.

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

실행 정책이 고정돼 있을 때(`S20`):

> IT 담당자님, 제 PC(Windows)의 그룹 정책이 PowerShell 실행 정책을 AllSigned 로 고정해 두어(MachinePolicy),
> 서명되지 않은 gatekit 스크립트(프로젝트의 .claude/gatekit/scripts 폴더에 있는 .ps1 파일)가 실행되지 않습니다.
> 이 폴더의 스크립트를 실행할 수 있게 허용해 주실 수 있나요?

프로그램 실행이 차단될 때(`S4`, `S5`):

> IT 담당자님, 제 PC(Windows)에서 (프로그램 경로) 실행이 조직 정책으로 차단됩니다(Windows 오류 1260).
> AppLocker 나 앱 제어 정책에서 이 프로그램을 사용자 권한으로 실행할 수 있게 허용해 주실 수 있나요?

## 9. CLI가 안 될 때: 스크립트를 직접 실행

CLI(`gatekit.py`)는 uv 와 `.venv` 가 있어야 시작됩니다. uv 가 깨졌거나 `.venv` 가 없을 때는
CLI를 부를 수 없으니 **스크립트를 직접** 실행하세요. 스크립트는 Windows 에 기본으로 있는
Windows PowerShell 5.1 만 있으면 됩니다.

```
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Lang ko
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Reinstall uv -Lang ko
powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1 -Install venv -Lang ko
```

이 스크립트도 안 돌면(파일이 없음 등) 파일을 되돌려야 합니다.

- `git clone`으로 받았으면(프로젝트 폴더에 `.git`이 있음): `git checkout .claude/gatekit/scripts`
- 압축 파일로 받았으면(Git이 없거나, Git은 있어도 프로젝트 폴더에 `.git`이 없음): 저장소를 다시 내려받아 `.claude/gatekit/scripts` 폴더의 파일을 덮어쓰세요.

setup도 같은 식으로 안내합니다. 이 창의 PATH에 Git이 있고 프로젝트 폴더에 `.git`(폴더나 파일)이
있을 때만 `git checkout ...` 명령을 보여 줍니다. Git이 없거나, Git은 설치돼 있어도 `.git`이 없으면
(압축 파일로 받은 경우 그 명령은 실패합니다) "저장소를 다시 내려받아 그 파일을 덮어쓰세요"를
보여 줍니다(`packages.json`, `.claude/settings.json`).
`common.ps1`을 읽지 못할 때는 Git이 있는지 확인할 방법이 없어서 두 가지를 함께 보여 줍니다.

## 10. 환경 점검 항목 (경로 길이, 실행 정책, 인터넷 표시, 실행 차단)

점검은 아무것도 바꾸지 않습니다. 레지스트리와 정책은 읽기만 하고, 표시 해제도 명령만 알려 줍니다.

| id | 보는 것 | 판정 | 할 일 |
|---|---|---|---|
| `S17` | 프로젝트 폴더 경로 길이 + 그 안에서 가장 긴 파일 경로 | 합이 259자를 넘으면 `warn`. 레지스트리의 `LongPathsEnabled`가 1이면 넘어도 `ok` | 더 짧은 폴더(예: `C:\dev`)로 옮기기 |
| `S20` | 그룹 정책이 고정한 실행 정책(`Get-ExecutionPolicy -List`의 `MachinePolicy`, `UserPolicy`) | `AllSigned`나 `Restricted`면 `fail`, 종료 코드 4 | IT 담당자에게 문의(8번의 문의문). 우회 금지 |
| `S8` | `scripts` 폴더의 `.ps1` 파일 전부에 "인터넷에서 받음" 표시가 있는지 | 있으면 파일 이름과 함께 `info`. 그룹 정책이 `RemoteSigned`면 `warn`, 종료 코드 2 | 아래 한 줄을 직접 실행 |
| `S4`, `S5` | `uv.exe`나 `.venv`의 `python.exe`가 있는데 Windows가 실행을 거부하는지 | 정책 때문이면(Windows 오류 1260, 4551) `fail`, 종료 코드 4 | IT 담당자에게 문의. 다시 설치해도 해결되지 않음 |

### 경로 길이 (`S17`)

Windows는 기본으로 260자 이상인 경로를 열지 못합니다(쓸 수 있는 길이는 259자). 프로젝트 폴더가
짧아 보여도 그 안의 긴 파일 경로를 더하면 넘을 수 있어서, setup은 둘을 더해 봅니다.

| 무엇 | 길이 |
|---|---|
| 저장소 파일 중 가장 긴 상대 경로 | 75자 |
| 일반 사용자의 `.venv`에서 가장 긴 상대 경로(만든 직후 55자, Python이 한 번 실행된 뒤 79자) | 79자 |
| setup이 쓰는 값(둘 중 큰 값) | 79자 |

그래서 프로젝트 폴더 경로가 **179자**를 넘으면 경고가 나옵니다(179 + 1 + 79 = 259).
개발용 도구(pyright, ruff)를 넣은 개발자의 `.venv`는 169자까지 가지만 일반 사용자에게는 생기지
않아 계산에 넣지 않았습니다. 개발자는 폴더 경로가 89자를 넘지 않게 하세요.

### 실행 정책 (`S20`)

gatekit의 훅과 스크립트는 `-ExecutionPolicy Bypass`를 붙여 실행합니다. 그런데 회사·학교가 그룹
정책으로 실행 정책을 `AllSigned`나 `Restricted`로 고정하면 이 옵션이 통하지 않아, 서명이 없는
gatekit 스크립트가 아예 실행되지 않습니다. 사용자가 허락해서 풀 수 있는 것이 아니므로 종료 코드 4입니다.

이런 PC에서는 보통 setup 스크립트 자체도 시작되지 않고 "이 시스템에서 스크립트를 실행할 수
없으므로 ... 파일을 로드할 수 없습니다"(영어: "... cannot be loaded because running scripts is
disabled on this system") 같은 오류가 먼저 나옵니다. 그 오류를 보면 직접 확인해 보세요.

```
Get-ExecutionPolicy -List
```

`MachinePolicy`나 `UserPolicy` 줄이 `AllSigned` 또는 `Restricted`이면 IT 담당자에게 문의하세요.
`Set-ExecutionPolicy`로 바꾸려 하지 마세요(그룹 정책이 우선이라 바뀌지 않습니다).

### "인터넷에서 받음" 표시 (`S8`)

브라우저로 받은 압축 파일을 풀면 안의 파일마다 이 표시가 붙습니다. gatekit은
`-ExecutionPolicy Bypass`로 실행하므로 보통은 표시가 있어도 그대로 동작합니다. 표시를 지우고
싶거나, 그룹 정책이 `RemoteSigned`라서 표시가 있는 파일이 실행되지 않을 때는 프로젝트 폴더에서
아래 한 줄을 직접 실행하세요. setup은 이 명령을 자동으로 실행하지 않습니다.

```
Get-ChildItem .claude\gatekit\scripts\*.ps1 | Unblock-File
```

### 실행 차단 (`S4`, `S5`)

`uv.exe`나 `.claude/gatekit/.venv/Scripts/python.exe`가 있는데도 Windows가 실행을 거부하면
(AppLocker 같은 정책, Windows 오류 1260 또는 4551) 다시 설치해도 같은 파일이 다시 막힙니다.
그래서 setup은 재설치를 권하지 않고 종료 코드 4와 문의문을 보여 줍니다. `.venv`도 지우거나 다시
만들지 않습니다. `python.exe`가 막히면 gatekit 훅도 동작하지 않습니다.

그 밖의 이유로 실행되지 않을 때(파일 손상, 접근 거부 등)는 정책 때문인지 구분할 수 없어서
전처럼 "실행해서 버전을 읽지 못했습니다"로 알리고 재설치를 안내합니다.

테스트용 환경 변수: `GATEKIT_SETUP_EXECUTION_POLICY`(예: `MachinePolicy=AllSigned;UserPolicy=Undefined`),
`GATEKIT_SETUP_LONG_PATHS`(`0` 또는 `1`), `GATEKIT_SETUP_EXEC_DENIED`(예: `uv;python`),
`GATEKIT_SETUP_PWSH_PACKAGES`. 실제 PC의 값을 바꾸지 않고 점검 결과만 바꿉니다.
`GATEKIT_SETUP_INSTALL_TIMEOUT`(초)은 winget 설치 한 번의 제한 시간 900초를 바꿉니다.
