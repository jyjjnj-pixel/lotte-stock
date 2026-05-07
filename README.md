# 롯데마트 전 지점 재고 조회 (웹 버전)

핸드폰, PC 어디서든 브라우저로 접속해서 사용하는 웹 페이지.

## 파일 구성

```
lotte_web/
├── main.py                    ← FastAPI 백엔드
├── requirements.txt           ← 파이썬 패키지 목록
├── render.yaml                ← Render 배포 설정
├── static/
│   └── index.html             ← 웹 페이지 (모바일 최적화)
└── README.md                  ← 이 파일
```

## 로컬에서 테스트하는 법 (선택사항)

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

그리고 브라우저에서 http://localhost:8000 접속

## 인터넷에 무료 배포 (Render.com)

### 1단계: GitHub에 코드 올리기

1. https://github.com 가입 (이미 있으면 건너뛰기)
2. New repository → 이름: `lotte-stock` (또는 원하는 이름) → Create
3. 이 폴더의 모든 파일을 그 저장소에 업로드
   - GitHub Desktop 앱이 제일 쉬움: https://desktop.github.com
   - 또는 GitHub 웹사이트에서 "uploading an existing file" 링크로 드래그

### 2단계: Render.com 배포

1. https://render.com 가입 (GitHub 계정으로 로그인 가능)
2. Dashboard → New + → Web Service
3. "Build and deploy from a Git repository" 선택 → Next
4. 방금 만든 GitHub 저장소 연결
5. 설정 (대부분 자동으로 채워짐):
   - Name: 원하는 이름 (URL이 됨)
   - Region: Singapore (한국에서 가장 가까움)
   - Branch: main
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Instance Type: **Free** ⭐
6. Create Web Service 클릭
7. 약 3~5분 기다리면 배포 완료
8. 상단에 `https://lotte-stock-XXXX.onrender.com` 같은 URL이 생김

### 3단계: 사용

배포된 URL을 핸드폰에서 열거나 친구한테 공유하면 끝!

## Render 무료 플랜 주의사항

- 15분 동안 사용 안 하면 서버가 잠듦
- 다음 접속 시 깨우는데 30~50초 소요 (첫 로딩 느림)
- 깨어난 후엔 정상 속도
- 한 달에 750시간 무료 (사실상 충분)

## 사이트 구조 바뀌어서 작동 안 할 때

`main.py`의 `parse_search_result` 함수를 수정하면 됨.
GitHub에 수정본 push하면 Render가 자동 재배포.
