# YULDION

화면 없는 AI 배우 핵심 엔진. 대본·상황에서 첫 행동을 준비하고, 목표와 관계를
유지하면서 자극·발견에 근거해 행동을 이어가거나 전환합니다. 해석·판단, 음성,
얼굴 모델은 각각 별도 어댑터로 연결합니다.

**현재 상태: 핵심 엔진·CLI·어댑터 계약과 테스트를 갖춘 개발 뼈대입니다.** 실제
음성/얼굴 모델은 포함하거나 연결하지 않았습니다. 로컬 GPU, RunPod, 학습 작업을
자동으로 찾거나 실행하지 않습니다. 미연결 상태에서는 가짜 연기를 만들지 않습니다.

## 빠른 시작

Python 3.11 이상. 핵심 엔진의 런타임 외부 의존성은 없습니다.

```bash
cd YULDION
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
yuldion validate --config examples/hamlet.json
yuldion doctor --config examples/hamlet.json
```

예제의 `doctor`는 세 모델이 미연결이므로 종료 코드 **2**를 반환하는 것이 정상입니다.
설정 검사만으로 모델 준비나 연기 품질이 검증된 것은 아닙니다.

설치 없이 소스에서 확인하려면:

```bash
PYTHONPATH=src python3 -m yuldion validate --config examples/hamlet.json
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 모델을 나중에 연결·교체하기

`examples/hamlet.json`을 `private/hamlet.local.json` 등으로 복사하고,
`reasoner`, `voice`, `face` 설정을 각각 설치된 어댑터의 `module:factory`로 바꿉니다.
`output_dir`도 원하는 영구 보존 경로로 명시하세요. 경로는 설정 파일 기준입니다.

```json
{
  "kind": "python",
  "entrypoint": "my_voice_adapter:create_voice",
  "options": {
    "checkpoint": "/workspace/models/selected-voice",
    "reference": "/workspace/private/voice-reference.wav",
    "device": "cuda:0"
  }
}
```

이 예의 `my_voice_adapter`는 포함된 모델이 아니라 구현할 어댑터 이름입니다.
같은 규격을 지키면 모델 종류·체크포인트를 바꿔도 엔진은 수정하지 않습니다.
교체는 **실행 사이**에 적용합니다. 실행 중인 학습 모델의 가중치를 덮어쓰거나,
실행 중 연결을 바꾸는 기능은 없습니다.

[어댑터 규격](docs/adapters.md) · [실행 구조](docs/architecture.md) ·
[RunPod 사용](docs/runpod.md)

## 실행

모델 어댑터가 설치·연결된 환경에서:

```bash
yuldion doctor --config private/hamlet.local.json
yuldion run --config private/hamlet.local.json --max-seconds 300 --json-events
yuldion inspect outputs/<run-id>/events.jsonl
```

`run`은 실제 모델을 호출하고, `inspect`는 저장된 JSONL만 출력합니다. `run`에
녹화 영상·작성된 심리 반응으로 대신 진행하는 경로는 없습니다.

실제 외부 텍스트를 입력하려면 `--events private/stimuli.jsonl`을 지정합니다.
다음과 같은 완성된 줄을 추가하면 안전한 발화 연결 지점에서 한 번만 반영합니다.
`after_segment: 1`은 두 번째 구절을 시작하기 전의 확인 지점입니다.

```json
{"id":"partner-1","kind":"external_text","text":"What makes you certain?","after_segment":1}
```

중간 구절 끼어들기, 마이크·카메라 관객 감지, 실시간 재생 화면은 이번 범위에 없습니다.

## 미리 준비되는 것 / 실행 중 생성되는 것

| 준비 | 실행 중 생성 |
|---|---|
| 대본·주어진 상황·목표·관계 | 현재 대사 해석·행동 제안·근거 검사 |
| 모델 가중치·인물 기준 자료 | 발성 지시·표정/시선 목표·음성·얼굴 프레임 |
| 어댑터의 제어 범위·보간 규칙 | 실제 보간 상태와 생성 결과 기록 |

첫 대사부터 생성된 해석과 대상 지향 행동이 필요합니다. 다음 구절은 확인 지점일
뿐이며, 전환 근거·새로움·현재 행동을 바꿀 필요성이 없으면 행동 ID와 얼굴/시선
목표를 유지합니다. 실제 상대 반응이 없을 때 결과는 `unobserved`로 남습니다.

목표·관계와 예제의 햄릿 해석은 잠정 리허설 설정입니다. 모델 감사도 오류가 있을
수 있으며, 제어값이 의도한 연기로 읽히는지는 실제 생성·청취·시각 평가가 필요합니다.

## 결과와 공개 범위

각 실행은 새 폴더에 `events.jsonl`, `state.json`, 음성 `.f32le`와 메타데이터,
PNG/JPEG 프레임을 저장합니다. 오디오는 변환 전 mono float32 PCM이며 프레임은
공통 샘플 시계를 참조합니다. 생성 지연과 재생 지연은 같지 않습니다.

GitHub에 넣는 것은 소스·문서·예제·테스트입니다. 가중치·개인 얼굴/음성·인증정보·
출력은 별도 보관하며 `.gitignore`에서 제외했습니다. 이 저장소는 YULDION 핵심 엔진의
공개 소스이며, 이전 실험 저장소·대화 기록·학습 결과 전체를 포함하는 백업은 아닙니다.
코드에는 MIT 라이선스를 적용하며 외부 모델·데이터의
사용 조건은 각각 따로 확인해야 합니다.

## CI 활성화

`docs/ci/test.yml.example`은 Python 3.11–3.13 테스트용 GitHub Actions 템플릿입니다.
현재 업로드 인증에 `workflow` 권한이 없어 자동 실행은 비활성 상태입니다.
해당 권한을 가진 환경에서 `.github/workflows/test.yml`로 복사하면 활성화됩니다.
