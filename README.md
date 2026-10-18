# YULDION

**독립 AI 배우 엔진.** 대본·주어진 상황을 받아 해석과 의도를 생성하고, 지속되는
행동을 목소리·표정·시선으로 연결하는 화면 없는 Python 프로그램입니다.
해석·음성·얼굴 모델을 각 어댑터로 연결하며, 로컬 또는 준비된 RunPod 환경에서 실행합니다.

```text
대본·상황·목표·관계 + 실제 관찰
  → 현재 대사의 해석·의도 제안 → 근거 검사 → 행동 유지/전환
  → 같은 행동에서 발성·표정·시선 지시 생성
  → 음성 생성 → 현재 음성과 같은 계획에 따른 얼굴 프레임 생성
  → 상태·출력·실행 기록
```

## 현재 구현 상태

핵심 엔진·CLI·어댑터 계약·기록과 자동 테스트를 갖춘 개발 버전입니다.
**실제 배우가 바로 실행되는 완성 모델 묶음은 아닙니다.**

| 구성 | 포함된 것 | 남은 연결/검증 |
|---|---|---|
| 배우 엔진 | 첫 대사 전 계획, 목표·관계 유지, 행동 전환 검사, 공통 오디오 시계 | 실제 해석·음성·얼굴 모델 통합 및 연기 평가 |
| 해석 모델 | OpenAI/로컬 선택, 전체 구절·관계 읽기, 근거 검사, 첫 대사 파이프라인 | OpenAI 실계정 검증·해석 품질 평가 |
| 음성 | 지연 로딩 CosyVoice3 포트 | 선택 모델·기준 음성·환경 연결, 실제 청취 |
| 얼굴 | 현재 음성·motor·gaze를 요구하는 backend 포트 | 의도→포즈 변환·실제 renderer backend 구현/연결 |
| 선택 도구 | 행동동사 분석·항목별 사용자 확정 CLI | 사용자가 지정한 언어모델 서버 연결 |

가중치·기준 음성·인물 이미지는 포함하지 않습니다. 미연결 상태에서는 가짜 연기를
만들지 않습니다. 모델 설치·학습·팟 생성은 실행자가 별도로 관리합니다.
로컬 Qwen3-8B의 실제 첫 대사 생성은 확인했으며, OpenAI 실계정 호출과
음성·얼굴을 포함한 전체 통합 실행은 아직 검증하지 않았습니다.

## OpenAI / 로컬 모델 선택해서 시작

```bash
# 설치 후, 둘 중 하나를 선택해 private 설정 생성
yuldion pipeline init --provider openai --scene examples/hamlet.json --config private/openai.local.json
# 또는 이미 준비한 llama.cpp 서버를 사용
yuldion pipeline init --provider local --scene examples/hamlet.json --config private/local.local.json

# 설정만 검사: 네트워크·모델 로드 없음
yuldion pipeline check --config private/openai.local.json
# OpenAI 키 숨김 입력 → 첫 대사 읽기·해석·의도·감사만 실제 실행
yuldion pipeline interpret --config private/openai.local.json --prompt-api-key
# 로컬 서버를 켠 경우
yuldion pipeline interpret --config private/local.local.json
```

OpenAI 사용자는 자기 API 키와 이용 요금이 필요합니다. 로컬 모드는 외부 API 키 없이
별도로 준비한 모델·장비를 사용합니다. **위의 interpret는 음성·얼굴을 로드하지 않습니다.**
전체 배우 실행은 해당 모델들이 연결된 뒤 `yuldion pipeline run`으로 시작합니다.

[처음부터 설치·키 설정·로컬 서버·실행·결과 확인](docs/pipeline.md)

독백 전체를 준비 맥락으로 읽고 `To die—to sleep, No more`를 해석하려면
`bash scripts/run_openai_soliloquy.sh`를 실행하세요. API 키는 숨김 입력하며
파일에 저장하지 않습니다. 모델 응답은 실행 후에만 생성됩니다.

## 핵심 엔진 설치·확인

Python 3.11 이상. 핵심 런타임 외부 의존성은 없습니다.

```bash
git clone https://github.com/yuldion/YULDION.git
cd YULDION
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
yuldion validate --config examples/hamlet.json
yuldion doctor --config examples/hamlet.json
```

`validate`는 구조만 검사합니다. 예제의 세 모델은 미연결이므로 `doctor` 종료 코드
**2**가 정상입니다. 어댑터 health도 로딩 성공·연기 품질을 보장하지 않습니다.

## 모델 연결과 실제 실행

`examples/hamlet.json`을 Git 제외 `private/hamlet.local.json`으로 복사합니다.
`reasoner`, `voice`, `face`에 별도 설치한 어댑터의 `module:factory`와 모델 옵션을
지정하세요. 출력 경로는 설정 파일 기준이므로 영구 보존할 위치를 명시합니다.
`examples/model-ports.template.json`은 음성·얼굴 옵션 문법 예제이며 완성 실행 설정이 아닙니다.

```bash
yuldion doctor --config private/hamlet.local.json
yuldion run --config private/hamlet.local.json --max-seconds 300 --json-events
yuldion inspect outputs/<run-id>/events.jsonl
```

`run`은 연결한 실제 모델을 호출합니다. `inspect`는 저장 기록을 읽습니다.
모델 교체는 실행 사이에 설정으로 적용합니다. 현재 학습 중인 파일을 수정하거나
실행 중 가중치를 자동 교체하지 않습니다.

[해석 모델 연결](docs/reasoner.md) · [어댑터 계약](docs/adapters.md) · [음성/얼굴 포트와 미검증 범위](docs/model-ports.md) ·
[아키텍처](docs/architecture.md) · [RunPod 실행](docs/runpod.md)

## 배우의 연속성

첫 대사부터 현재 대본과 상황을 근거로 생성한 해석·행동이 필요합니다.
목표·관계는 실행 동안 유지합니다. 새 구절은 확인 지점이며 그 자체로 행동을
바꿀 이유가 아닙니다. 새 자극 또는 발견에 근거와 새로움·전환 필요성이 있어야
행동 ID를 바꿉니다. 행동 유지 시 얼굴·시선 목표도 유지하며 현재 발음을 준비합니다.
모델의 근거 감사는 오류가 있을 수 있으며 의미적 타당성을 엔진이 증명하지는 않습니다.

실제 상대 텍스트는 `--events private/stimuli.jsonl`로 입력합니다.

```json
{"id":"partner-1","kind":"external_text","text":"What makes you certain?","after_segment":1}
```

두 번째 구절 전 확인 지점부터 해당 자극을 한 번 반영합니다. 반응을 관찰하지
않았으면 결과는 `unobserved`로 유지합니다. 마이크·카메라 관객 감지와 중간 발화
끼어들기, 실시간 화면·오디오 장치 재생은 아직 없습니다. 생성 속도와 실시간 재생
지연은 다르며 저지연 연기 성능을 검증한 상태는 아닙니다.

## 준비 데이터와 실행 중 생성 결과

| 준비 | 실행 중 생성 |
|---|---|
| 대본·주어진 상황·목표·관계 | 현재 해석·의도·행동 제안·근거 검사 |
| 모델 가중치·정적 인물 기준 자료 | 발성·표정·시선 지시, PCM·얼굴 프레임 |
| 어댑터 제어 범위와 보간 방식 | 보간 상태·결과·기술 피드백·실행 기록 |

햄릿 예제의 목표·관계는 작성자가 제안한 잠정 리허설 가설이며 사용자 확정 분석이
아닙니다. 같은 사실/가설 구분을 자신의 입력에도 적용하세요.

## 선택 기능: 행동동사 분석

`yuldion-action-verbs`는 **별도 실행하는 리허설 도구**입니다. 욕구·초목표·관계·유닛·
행동 동사 후보·선별·행위 구체화·수행 검토를 하나씩 사람이 확정합니다.
이 방법이 YULDION 전체의 대본 분석을 정의하거나 엔진 실행의 선행 조건이 되지는 않습니다.

```bash
yuldion-action-verbs --help
# 설치 없이도 독립 실행 가능
PYTHONPATH=src python3 -m yuldion.tools.action_verbs --help
```

코드는 `src/yuldion/tools/action_verbs/`에 있으며, 핵심 엔진은 이를 import하거나
자동 실행하지 않습니다. 별도 언어모델 서버가 필요하며 분석 결과를 엔진에 자동
주입하는 기능도 없습니다. 기존 `script-analyzer` 저장소와 의존 관계가 없습니다.

[선택 도구 사용법·단계별 확인 절차](docs/action-verb-analysis.md)

## 테스트와 설치 검증

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

자동 테스트는 데이터 계약·상태 전이·승인 순서를 테스트 전용 응답으로 검증합니다.
실제 해석 능력·목소리·인물 닮음·시선·연기는 모델 연결 후 별도로 평가해야 합니다.
GitHub Actions는 `docs/ci/test.yml.example` 템플릿으로 제공합니다. 기존 업로드 인증에
`workflow` 권한이 없어 자동 CI는 활성화하지 않았습니다.

## 결과·저장·라이선스

실행마다 새 폴더에 `events.jsonl`, `state.json`, mono float32 little-endian PCM
`.f32le`와 메타데이터, PNG/JPEG 프레임을 저장합니다. 같은 plan ID와 sample clock을
사용하며, 저장 성공이 실제 장치 재생이나 연기 품질 검증을 뜻하지 않습니다.

공개 저장소에는 배포 소스·규격·설치법·공개 예제·테스트를 포함합니다. 모델 가중치,
개인 음성·얼굴 자료, 인증정보와 생성 결과는 Git에서 제외합니다. 기존 연구 전체의
공개나 백업을 대신하지 않습니다. 코드는 MIT이며 외부 모델·데이터의 조건은 각각
따로 확인해야 합니다.
