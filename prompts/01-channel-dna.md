# 01. Channel DNA

## 입력

- Instagram 계정: `<USERNAME_OR_PROFILE_URL>`
- 수집 개수: `<MAX_RESULTS, 수업에서는 10 이하 권장>`

## 요청

1. `apify/instagram-reel-scraper`의 현재 상세 정보와 입력 스키마를 먼저 확인한다.
2. 공개 Reel을 지정한 개수만 수집한다. 영상 파일은 다운로드하지 않는다.
3. 원본 결과를 `data/raw/<USERNAME>-reels-<YYYYMMDD>.json`에 저장한다.
4. 다음 필드를 정규화해 `data/processed/<USERNAME>-reels-<YYYYMMDD>.csv`에 저장한다.
   - `source_url`
   - `published_at`
   - `caption`
   - `transcript`
   - `views`
   - `likes`
   - `comments`
   - `shares`
   - `duration_seconds`
   - `actor_id`
   - `collected_at`
5. 누락된 값은 추측하지 않고 `null`로 둔다.
6. 성과 상위 20%와 나머지를 비교해 hook, 구조, 길이, CTA에서 함께 관찰된 차이를 정리한다.
7. 결과를 `results/channel-dna-<USERNAME>-<YYYYMMDD>.md`에 저장한다.

보고서는 확인된 관찰과 해석을 별도 섹션으로 나눈다. 공개 지표만으로 성공 원인을 단정하지 않는다.
