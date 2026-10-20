# YULDION

대본·주어진 상황을 읽고, 인물의 목표와 관계를 유지하면서 **뜻 → 의도 → 행동 →
발성·표정·시선 지시**를 연결하는 독립 Python AI 배우 엔진입니다.
OpenAI API 또는 사용자가 준비한 로컬 모델 서버를 선택합니다.

```text
전체 대본 분석 → 모든 줄의 뜻·의도·행동 저장 → 의미 검수
  → 검수된 계획 조회 → 발성·motor 생성 → 선택한 음성·얼굴 어댑터
                오류 → 완료된 단계 보존 → 실패한 단계/줄부터 제한된 자동 복구
```

## 현재 되는 것과 남은 것

| 구성 | 구현/검증 | 남은 일 |
|---|---|---|
| 대본 파이프라인 | 전체 분석·모델 의미 검수·줄별 계획·체크포인트·자동 재개. 실제 API에서 응답 직후 연결 오류 1회를 주입해 해당 줄부터 끝까지 복구 확인 | 해석·연기의 사람 검수. 모델 검수는 객관적 정답이나 사람 승인 아님 |
| 공통 엔진 | 지원 기능 검사, 요청/전달/적용 보고 구분, PCM과 얼굴 작업 분리, 공통 샘플 시계 | 실제 재생기·장치 시계·동기화 검수 |
| 음성 | 기본 CosyVoice 포트와 보존 B/v66 실행기용 전용 연결 포트 | 준비된 실제 실행기 factory 연결, 합성·음색·지연·제어 효과 검수 |
| 얼굴 | 보존 B/v10/v30/v36 구성용 전용 포트, 완성 발화 PCM 입력, motor/시선 적용 보고 검사 | 실제 renderer factory 연결, 시각 검수. v30은 발화 전체가 필요하며 온라인 얼굴 모델 아님 |

가중치·개인 음성·얼굴 자료·인증정보·실행 결과·연구 전체는 포함하지 않습니다.
**설치만으로 완성된 배우가 바로 구동되는 모델 묶음은 아닙니다.** 전용 포트의 CPU
계약 테스트와 실제 모델 연결·청취·시각 검증은 별개입니다. 자동 다운로드·학습·GPU 생성은 없습니다.

## 1. 설치

Python 3.11 이상. 핵심 엔진은 표준 라이브러리만 사용합니다. 각 모델 런타임은
별도 추론 환경에 준비해야 하며 학습 환경을 변경하지 마세요.

```bash
git clone https://github.com/yuldion/YULDION.git
cd YULDION
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
yuldion validate --config examples/hamlet.json
```

예제 모델은 미연결입니다. `yuldion doctor --config examples/hamlet.json`의 종료 코드
2는 이 예제에서 예상되는 결과입니다. health가 configured라고 해도 실제 추론 성공은 아닙니다.

## 2. 전체 대본 → 검수 → 연기 지시

```bash
yuldion pipeline init --provider openai --scene examples/hamlet-soliloquy.json \
  --config private/openai.local.json
python -m yuldion.tools.inspector.server --config private/openai.local.json --port 8794
```

브라우저에서 **http://127.0.0.1:8794/** 를 엽니다. 키를 숨김 입력하고 한 번 시작하면
전체 대본의 연기 지시까지 진행합니다. 이미 완료된 분석·검수·줄은 재사용합니다.
서버가 켜져 있는 동안 키를 메모리에 유지하며 파일/브라우저 저장소에는 저장하지
않습니다. `키 지우기` 또는 서버 종료로 해제됩니다. API 이용료는 별도입니다.

로컬 모델을 쓰려면 init에서 `--provider local --endpoint http://127.0.0.1:8080/v1/chat/completions`
를 선택하고 별도로 준비한 llama.cpp 등의 서버를 사용합니다. 모델을 자동 설치하지 않습니다.

관찰 화면은 선택 기능입니다. CLI로 각 단계를 독립 실행할 수도 있습니다.

```bash
yuldion pipeline prepare --config private/openai.local.json --prompt-api-key \
  --output-dir outputs/analysis-01 --bound-config private/prepared.local.json --allow-draft
yuldion pipeline review --config private/prepared.local.json --prompt-api-key \
  --output-dir outputs/review-01 --bound-config private/reviewed.local.json
yuldion pipeline plan --config private/reviewed.local.json --prompt-api-key \
  --output-dir outputs/plans-01
```

실행 시 뜻·의도·행동을 재분석하지 않고 저장된 score를 조회해 `perform`만 호출합니다.
목표·관계는 유지하고 현재 자극/발견이 기존 행동을 불충분하게 만들 때만 전환합니다.
신체 수행·촬영·사람 승인 단계는 수행했다고 꾸미지 않습니다. 별도 수동 리허설 도구
`yuldion-action-verbs`는 선택 기능이며 기존 script-analyzer 저장소와 의존 관계가 없습니다.
자동 prepare는 해당 순서·검사 코드를 명시적으로 재사용합니다.

형식 오류는 해당 줄에서 최대 3회 시도합니다. 관찰 서버의 감독자는 일시 연결/요청제한
오류나 저장된 모델 응답 형식 오류에서 최대 3개 작업 시도를 관리하며, 인증 실패·의미
검수 지적·해시 불일치는 자동으로 통과시키지 않습니다. CLI 단일 단계는 수동 재개 옵션을
제공합니다. 호스트 강제 종료/재부팅의 무인 복원·무제한 재시도·중복 과금 방지는 보장하지 않습니다.

[설정·재개·오류 복구 상세](docs/pipeline.md)

## 3. 음성·얼굴 연결 준비

전용 포트는 **이미 준비된 추론 실행기**에 연결하는 경계입니다. 예제의 factory는
자리표시자이며 실제 서버/가중치가 제공되는 것이 아닙니다.

| 포트 | 안내 | 주요 제한 |
|---|---|---|
| 보존 B 음성 | [규격·설치 환경·수명](docs/b-voice-v66.md), [voice 옵션 예제](examples/b-voice-v66.template.json) | 자연어 발성 효과는 미검증. 정확한 숫자 pitch/volume/streaming speed 제어 미지원. 실험 기능은 명시적 허용 필요 |
| Hamlet 얼굴 | [입출력·좌표·지원 범위](docs/hamlet-face-port.md) | 작은 머리 회전·주시점·눈썹 잔차 전달은 실험적. 의미적 시선 대상은 명시적 위치 매핑 필요. 독립 목·어깨 제어 미지원 |

`private/reviewed.local.json`의 voice/face 항목을 각 문서의 entrypoint와 실제 prepared
factory로 설정하세요. 개인 자산 경로와 환경 manifest는 private 안에 둡니다.
원문·목표·준비 분석·검수 해시를 임의로 변경하지 마세요.

```bash
# 어댑터와 추론 환경을 별도로 준비한 후에만 실행
# 음성만: 얼굴 플러그인을 생성/로드하지 않음
yuldion run --config private/reviewed.local.json --face-mode off --max-seconds 300 --json-events
# 음성 + 얼굴: 기본은 별도 얼굴 큐
yuldion run --config private/reviewed.local.json --face-mode async --max-seconds 300 --json-events
```

이 명령은 실제 모델을 호출해 PCM·프레임을 저장합니다. 스피커/디스플레이 플레이어가
포함된 명령은 아닙니다. 앱은 `Engine.run_streaming(audio_sink, ...)`로 PCM을 받아
재생 스케줄을 관리할 수 있습니다. 얼굴 큐 포화 시 얼굴 요청만 버리고 기록합니다.
발화 전체가 필요한 모델에는 `audio_complete=True`인 전체 PCM을 보냅니다.
음성을 먼저 내보내는 것과 얼굴/입모양이 실제로 동기화된다는 것은 다릅니다.

지원 선언, 요청값, 실제 전달값, 렌더러 적용 보고, 효과 검증을 구분합니다.
미지원 요청을 감정 프리셋·저장 궤적·조용한 피치/속도 후처리로 대체하지 않습니다.
기존 생성 motor와 모델의 물리 단위가 맞지 않으면 먼저 연결 규격을 맞춰야 합니다.

[공통 어댑터·PCM 시계·적용 기록](docs/adapters.md) · [RunPod 추론 준비](docs/runpod.md)

## 다음 단계와 학습

먼저 **준비된 실제 실행기 연결과 짧은 대사 검수**가 필요합니다. 어댑터가 있다는 이유로
목소리/얼굴을 다시 학습할 필요는 없습니다. 제어 효과나 온라인 얼굴 처리에 추가 학습이
필요한지는 연결·기준 비교 후 결정합니다. [담당별 다음 단계](docs/integration-roadmap.md).
현재 학습이 완료됐다고 이 저장소에서 보장하지 않습니다.

## 테스트·기록·라이선스

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

자동 테스트는 CPU fixture를 사용합니다. 실제 목소리·닮음·연기·저지연 성능 검증이
아닙니다. 실제 API 장애 주입 검증은 API 호출 후 클라이언트 연결 예외를 넣는 검사이며,
외부 서비스 장애를 일으킨 것이 아닙니다. 테스트 도구는 `tools/verify_recovery.py`에 있습니다.
GitHub Actions 템플릿은 `docs/ci/test.yml.example`이며 활성화 여부와 구분합니다.

실행 결과는 `outputs/`에 기록하고 Git에서 제외합니다. 코드는 MIT이며 외부 모델·데이터
라이선스는 별도로 따릅니다. 이 저장소 배포는 연구 전체의 공개/Drive 백업을 대신하지 않습니다.
