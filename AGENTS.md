# Apify Instagram Workshop

## 프로젝트 목표

- Claude Code 또는 Codex와 Apify를 사용해 공개 Instagram Reel을 수집하고 분석한다.
- 3시간 안에 Channel DNA, Viral Radar, Reference to Script 흐름을 실습한다.
- `AGENTS.md`를 공통 지침의 단일 원본으로 사용한다.

## 범위

- 우선 사용: `apify/instagram-reel-scraper`, `apify/instagram-search-scraper`.
- 필요할 때만 사용: `apify/instagram-scraper`.
- 이번 수업에서 제외: Meta Insights API, 인포크 자동화, n8n, 자동 게시, 영상 편집, 타인 영상 다운로드와 재사용.

## 작업 원칙

- 실행 전 Actor 상세 정보와 현재 입력 스키마를 확인한다. 기억에 의존해 입력 필드를 만들지 않는다.
- 첫 실행은 결과 10개 이하로 제한한다. 입력과 결과를 확인한 뒤 범위를 늘린다.
- `data/raw/`의 원본은 덮어쓰지 않는다. 정규화 결과는 `data/processed/`, 분석 결과는 `results/`에 저장한다.
- 확인한 관찰과 해석을 분리한다. 공개 지표만으로 성과의 원인을 단정하지 않는다.
- 누락된 값은 추측하지 않고 `null` 또는 `unknown`으로 남긴다.
- 모든 결과에는 원본 URL, 수집 시각, 사용한 Actor ID를 남긴다.

## 도구 선택

- Actor 검색, 현재 입력 스키마 확인과 실행에는 Apify 공식 플러그인 또는 MCP를 우선한다.
- Apify 제품 문서와 API 문서를 확인할 때는 `apify_docs` 또는 `apify-docs` MCP를 사용한다.
- 공개 GitHub 저장소의 구조와 구현을 확인할 때만 `deepwiki` MCP를 사용한다.
- DeepWiki 답변은 저장소 코드와 문서를 요약한 2차 자료로 취급한다. 중요한 판단은 원본 저장소에서 다시 확인한다.
- 비공개 저장소를 DeepWiki에 전달하지 않는다.

## 데이터와 비밀정보

- `APIFY_TOKEN`은 환경변수 또는 로컬 `.env`에서만 읽는다.
- 토큰, 쿠키, 세션, 개인 식별 정보는 커밋하거나 결과 파일에 복사하지 않는다.
- 공개 계정의 공개 데이터만 수집하고 플랫폼 약관과 관련 법규를 따른다.
- 영상 파일을 다운로드하거나 재배포하지 않는다. URL, 공개 지표, 캡션과 제공된 transcript만 분석한다.

## 분석 규칙

- `viral_score` 같은 점수는 휴리스틱임을 명시하고 계산식을 함께 기록한다.
- 비교 기준은 같은 계정 또는 비슷한 규모의 계정에서 최근 콘텐츠 중앙값을 우선한다.
- "성공 원인" 대신 "성과와 함께 관찰된 차이"라고 표현한다.
- 대본 생성은 표현을 복제하지 않고 hook, tension, payoff, demonstration, CTA 구조만 추출해 재구성한다.

## 디렉터리

- `prompts/`: 수업에서 순서대로 실행할 프롬프트.
- `data/raw/`: Apify 원본 결과. Git에서 제외한다.
- `data/processed/`: 정규화 데이터. Git에서 제외한다.
- `results/`: 분석 보고서와 생성 대본. Git에서 제외한다.

## 완료 기준

- 작은 샘플 실행이 성공하고 결과 행 수를 확인했다.
- 원본과 정규화 결과가 분리되어 있다.
- 분석 결과에 근거 URL과 지표가 포함되어 있다.
- 비밀정보가 Git 변경 내역에 없다.

## Code Review Rules

- 비밀정보나 수집 원본이 추적되면 차단한다.
- 현재 Actor 스키마를 확인하지 않은 하드코딩 입력을 지적한다.
- 공개 지표를 인과관계로 표현하거나 누락값을 채운 분석을 지적한다.
- 출처 URL, 수집 시각, Actor ID가 없는 결과 형식을 지적한다.
