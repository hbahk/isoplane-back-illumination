# K-SPEC v09 design review

검토용 3D 모델입니다. 실제 분광기 내부 치수, grating 간섭, 고정 강도 및 파손 시 낙하 방지는 검증되지 않았습니다. 승인된 제작 도면이 아닙니다.

## GitHub Pages 게시 방법

1. 게시할 GitHub 저장소를 만듭니다. GitHub Free에서는 공개(Public) 저장소를 사용합니다.
2. 이 폴더의 내용물을 저장소 최상위에 올립니다. ZIP 자체나 이 폴더를 한 단계 더 감싸서 올리지 않습니다. 최상위에 index.html이 보여야 합니다.
3. Settings → Pages → Build and deployment → Source: Deploy from a branch.
4. Branch: main, Folder: / (root)를 선택하고 Save합니다.
5. Pages 설정 화면에 표시되는 사이트 주소를 공유합니다. 첫 배포에 몇 분이 걸릴 수 있습니다.

게시 예정 저장소: hbahk/isoplane-back-illumination

게시 후 예상 주소 (아직 배포되지 않음): https://hbahk.github.io/isoplane-back-illumination/

## 포함 파일

- index.html: 모델과 3D 프로그램을 내장한 독립형 HTML
- review.html: 검토 결과와 확인되지 않은 사항
- parts.csv: 부품표
- wiring.svg: 기능 배선도 (확정 회로도 아님)
- preview.png: 정적 미리보기
- .nojekyll: 별도 Jekyll 변환 없이 정적 파일 게시

데스크톱의 WebGL 지원 브라우저를 권장합니다. 로컬 파일로도 열 수 있습니다. 원본 매뉴얼·구매 페이지·개인 경로·CAD 제작 파일은 배포본에 포함하지 않았습니다. 다만 HTML에는 표시용 3D 형상 데이터가 들어 있으므로 웹 공개 시 그 데이터도 공개됩니다.

GitHub Pages 일반 공개 사이트에는 열람자별 비밀번호나 접근 제한이 없습니다. 비공개 저장소만으로 웹사이트가 비공개가 되는 것은 아닙니다.

https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site
