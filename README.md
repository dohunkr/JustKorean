# Just Volleyball 비공식 한글 패치 (JustKorean)

Steam 게임 **Just Volleyball**의 비공식 한국어 패치 및 원클릭 설치기입니다.

## 주요 특징

- **원클릭 설치기 (`JustKorean_Installer.exe`)**: 별도 프로그램이나 Python 설치 없이 실행 한 번으로 패치 설치
- **자동 Steam 경로 탐지 & 백업**: 원본 `volleyball.pck`를 `volleyball.pck.bak`으로 자동 백업하며, 언제든지 원클릭으로 원본 복원 가능
- **한글 폰트 내장**: 오픈소스 한글 폰트(`Pretendard`, `Galmuri9`) 적용으로 모든 메뉴, 픽셀 UI, 게임 가이드가 깨짐 없이 출력
- **전체 UI / 게임 데이터 번역**:
  - 메인 메뉴, 설정, 로비, 일시정지 메뉴, HUD, 리플레이 뷰어
  - 게임 방법 가이드 (`how_to_text.json`), 튜토리얼 및 드릴
  - 업적, 칭호(500+종), 액세서리(70+종), 칭호 효과(50+종)

## 설치 방법

1. [Releases](../../releases) 페이지에서 최신 `JustKorean_Installer.exe`를 다운로드합니다.
2. `JustKorean_Installer.exe`를 실행합니다.
3. 게임 폴더가 자동으로 감지되었는지 확인합니다. (감지되지 않으면 `찾아보기...`로 `just volleyball` 폴더를 선택하세요.)
4. **[한글 패치 설치]** 버튼을 클릭합니다.
5. 완료 메시지가 뜨면 Steam에서 게임을 실행합니다.

## 패치 제거 (원본 복원)

- `JustKorean_Installer.exe`를 실행한 뒤 **[원본 복원 (제거)]** 버튼을 클릭하면 백업된 원본 `volleyball.pck`로 복원됩니다.
- 또는 Steam에서 `게임 속성 → 설치된 파일 → 게임 파일 무결성 검사`를 실행해도 원본으로 복원됩니다.

## 소스에서 실행 / 빌드

```bash
pip install -r requirements.txt
python installer.py
```

단일 실행 파일(`dist/JustKorean_Installer.exe`) 빌드:

```bash
pyinstaller --onefile --windowed --name JustKorean_Installer --add-data "patch_data;patch_data" installer.py
```

## 라이선스 및 안내

- 본 프로젝트의 패처 및 번역 스크립트는 [MIT License](LICENSE)를 따릅니다.
- 포함된 폰트(`Pretendard`, `Galmuri9`)는 SIL Open Font License 1.1 (OFL)을 따릅니다.
- 게임 원본 리소스나 바이너리는 배포하지 않으며, 사용자의 로컬 게임 파일을 패치하는 방식으로 동작합니다.
