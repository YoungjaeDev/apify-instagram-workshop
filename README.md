# Apify Instagram Workshop

Claude Code와 Apify로 Instagram Reel 수집, 분석, 대본 생성을 실습하는 3시간 워크숍입니다.

## 결과물

- 내 채널의 공개 Reel을 비교한 Channel DNA
- 레퍼런스 계정과 키워드 기반 Viral Radar
- 레퍼런스 구조를 내 채널 문법으로 재구성한 신규 대본

Meta Insights API, 인포크 자동화, 자동 게시와 영상 편집은 이번 범위에 포함하지 않습니다.

## 수업 전 준비

### 필수

1. [Claude Code](https://code.claude.com/docs/en/overview)를 설치하고 로그인합니다.
2. [Apify](https://console.apify.com/sign-up)에 가입합니다. MCP의 대화형 OAuth만 사용할 때는 API 토큰이 필요하지 않습니다.
3. Claude Code에서 공식 Apify 플러그인을 설치합니다.

```text
/plugin marketplace add apify/apify-claude-code-plugin
/plugin install apify@apify
```

4. Claude Code를 다시 시작하고 다음 요청으로 연결을 확인합니다.

```text
Apify에서 apify/instagram-reel-scraper의 현재 입력 스키마와 가격 모델을 확인해줘.
```

Actor를 처음 실행할 때 브라우저가 열리면 Apify에 로그인하고 OAuth 권한을 승인합니다.

### API 토큰이 필요한 경우

CLI, SDK, CI처럼 브라우저 OAuth를 사용할 수 없는 환경에서만 필요합니다.

1. Apify Console의 [API & Integrations](https://console.apify.com/account/integrations)에서 토큰을 확인하거나 새로 만듭니다.
2. `.env.example`을 `.env`로 복사하고 값을 입력합니다.
3. `.env`를 Git에 추가하지 않습니다.

```bash
cp .env.example .env
```

### Codex를 사용하는 경우

Apify CLI로 로그인한 뒤 공식 MCP를 Codex에 설치합니다.

```bash
brew install apify-cli
apify login
apify mcp install codex
```

공식 Apify Agent Skill도 함께 사용할 수 있습니다.

```bash
npx skills add https://github.com/apify/agent-skills --skill apify-ultimate-scraper
```

## 수업에서 사용할 Actor

| 순서 | Actor | 용도 |
|---|---|---|
| 1 | `apify/instagram-reel-scraper` | 내 채널과 지정 계정의 공개 Reel 수집 |
| 2 | `apify/instagram-search-scraper` | 키워드, 계정, 해시태그 기반 레퍼런스 탐색 |
| 3 | `apify/instagram-scraper` | 프로필, 게시물, 댓글이 추가로 필요할 때만 사용 |

Actor의 입력 스키마와 가격은 변경될 수 있습니다. 실행할 때 Apify에서 현재 정보를 다시 확인합니다.

## 3시간 진행 순서

| 시간 | 실습 |
|---|---|
| 0:00-0:20 | 구조 이해, 계정과 플러그인 확인 |
| 0:20-0:50 | 작은 샘플 수집과 데이터 확인 |
| 0:50-1:25 | Channel DNA 생성 |
| 1:25-2:00 | Viral Radar 생성 |
| 2:00-2:40 | Reference to Script 실습 |
| 2:40-3:00 | 결과 검토와 다음 단계 정리 |

`prompts/`의 파일을 번호 순서대로 열고 `<...>` 자리만 바꿔 실행합니다.

## 파일 구조

```text
.
├── AGENTS.md
├── CLAUDE.md
├── prompts/
│   ├── 01-channel-dna.md
│   ├── 02-viral-radar.md
│   └── 03-reference-to-script.md
├── data/
│   ├── raw/
│   └── processed/
└── results/
```

`CLAUDE.md`는 `@AGENTS.md`를 import합니다. Claude Code와 Codex가 같은 프로젝트 지침을 중복 없이 사용합니다.

## 주의사항

- Apify는 공개 관찰 데이터를 수집합니다. reach, saves, 평균 시청시간 같은 소유자 전용 지표는 Meta Insights API의 영역입니다.
- 공개 데이터만으로 바이럴의 인과관계를 증명할 수 없습니다.
- 타인의 영상을 다운로드하거나 재사용하지 않습니다.
- 계정 상태와 Instagram의 공개 범위에 따라 과거 Reel 전체가 수집된다고 보장할 수 없습니다.

## 공식 문서

- [Apify MCP](https://docs.apify.com/integrations/mcp)
- [Apify Claude Code Plugin](https://github.com/apify/apify-claude-code-plugin)
- [Apify Agent Skills](https://github.com/apify/agent-skills)
- [Claude Code의 AGENTS.md 연동](https://code.claude.com/docs/en/memory#agents-md)
- [Codex의 AGENTS.md 탐색 규칙](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
