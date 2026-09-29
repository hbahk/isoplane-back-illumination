# K-SPEC v10 design review

[Open the interactive model](https://hbahk.github.io/isoplane-back-illumination/) · [Previous v09](https://hbahk.github.io/isoplane-back-illumination/v09.html)

LM2370 12V 150 mm를 공통으로 사용하는 두 교체형 암의 검토용 모델입니다.

- Metaphase MB-TBL2X2-B-24-ILZ 직접 장착: 모델 삽입 두께 약17.9 mm. 제공된 STEP 형상을 사용합니다.
- 백업 PTFE 32×32 mm + LED 2개: 모델 삽입 두께8.5 mm.
- 같은 가이드·외부 flag 방식 센서·지지대를 공유합니다. 두 암의 최대 안내 레일 폭은68 mm입니다.
- X ±20 mm / Y ±5 mm 검토 범위. 그 밖의 기구 슬롯 범위는 사용 가능하다고 검증되지 않았습니다.

모델 부품의 지정 자세·이동 표본과 브라우저 제어를 확인했습니다. 실제 분광기 개구부, grating 회전 범위, 본체 나사, 강도·저온·차광, 전선 거동 및 파손 시 포획은 검증되지 않았습니다. 제작·장착이 승인된 도면이 아닙니다. [검토 범위](review.html)를 먼저 확인하세요.

## Files

- `index.html`: self-contained WebGL viewer, both variants.
- `review.html`: design changes, assumptions, and verification limits.
- `parts.csv`, `additional-parts.csv`: print parts and changed hardware.
- `wiring.svg`, `wiring-backup.svg`: functional power/control diagrams, not finalized pin-level schematics.
- `preview.png`: static preview.
- `v09.html` and `*-v09.*`: archived prior review.

인터넷 없이 HTML을 직접 열 수도 있습니다. 표시용 메시는 HTML에 포함되어 공개됩니다. 원본 사용자 STEP, 원본 매뉴얼, 구매 파일, 개인 경로, 이메일은 이 공개 패키지에 포함하지 않습니다. Three.js/OrbitControls notices are in THIRD_PARTY_NOTICES.txt.
