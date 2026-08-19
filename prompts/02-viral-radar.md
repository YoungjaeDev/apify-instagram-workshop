# 02. Viral Radar

## 입력

- 레퍼런스 계정: `<PROFILE_URLS>`
- 검색 키워드: `<KEYWORDS>`
- 기간: `<DAYS, 예: 30>`
- 후보 개수: `<MAX_RESULTS, 수업에서는 30 이하 권장>`

## 요청

1. 필요한 Actor의 현재 상세 정보와 입력 스키마를 먼저 확인한다.
2. 지정 계정은 `apify/instagram-reel-scraper`, 검색은 `apify/instagram-search-scraper`를 우선 사용한다.
3. 영상 파일은 다운로드하지 않고 공개 지표, URL, 캡션과 제공된 transcript만 수집한다.
4. 각 콘텐츠를 해당 계정의 최근 Reel 조회수 중앙값과 비교한다.
5. 다음 휴리스틱을 기본값으로 사용하되, 데이터가 부족하면 계산하지 않는다.

```text
viral_score = reel_views / creator_recent_median_views
```

6. 게시 후 경과 시간을 함께 표시하고 상위 후보 10개를 선정한다.
7. 결과를 `results/viral-radar-<YYYYMMDD>.md`에 저장한다.

각 후보에는 원본 URL, 게시 시각, 공개 지표, 비교 기준, 점수 계산식, 추천 이유를 포함한다. `viral_score`는 인과관계가 아닌 탐색용 휴리스틱이라고 명시한다.
