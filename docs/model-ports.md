# 음성·얼굴 연결 준비 — 2026-10-18

이번 확인은 로컬 소스 읽기와 가벼운 계약 테스트만 수행했습니다. 원격 프로세스,
GPU, 학습 파일, 모델 가중치, 모델 선택 상태를 확인하거나 수정하지 않았습니다.
따라서 아래 항목은 **확인한 코드의 인터페이스**이며 현재 학습 중인 모델 또는
최종 채택 모델이라는 뜻이 아닙니다. 기존 연구 전체를 공개 저장소로 옮기지 않습니다.

## 확인한 연결 지점

| 연구 코드 | 입력 | 출력 | 연결 시 주의 |
|---|---|---|---|
| `hamlet_voice_finetune_v02/infer.py` | CosyVoice3 모델 디렉터리, 기준 WAV, 텍스트, instruction | `tts_speech` mono tensor, `model.sample_rate` | 기존 비교용 스크립트는 텍스트·지시가 고정되어 있으므로 직접 실행하지 않음 |
| `hamlet_voice_intent_v10/voice.py` | `stream(text, instruction, cancel, silent_limit)` | `(float PCM array, monotonic arrival)` iterator | silence filter/취소용 runtime patch가 있음. 기본 CosyVoice 어댑터와 동등한 재현이라고 부르지 않음 |
| `hamlet_voice_joint_v16/actor_stream.py` | 선택 runtime 구성과 실험용 가중치/부가 어댑터 | `actor.voice.stream(...)`, 음성·표정 관련 profile | 모듈 전역 경로와 runtime 설정이 결합됨. 공개 엔진에서 자동 import하지 않음 |
| `hamlet_face_alignment_voice_v31/live_pipeline.py` | 수신 PCM, mouth delta, 보존된 motion/profile | LivePortrait RGB 프레임 | gaze가 기존 sample clock/profile을 따름. 새 의도에 따른 gaze 입력 아님 |
| `hamlet_face_alignment_voice_v31/fast_face.py` | `frame(baseline, modified)`, 각각 `(21,3)` 포즈 | `(base RGB, final RGB, timing/protection stats)` | 자연어 의도→포즈 변환은 이 렌더러의 기능이 아님 |

이 목록은 API를 조사한 연구 폴더 이름입니다. 사적 경로·모델 위치·자산 ID는
설정 예제에 넣지 않았습니다. 체크포인트 SHA와 실제 런타임 버전은 모델 확정 후
Git 제외 manifest에 기록해야 합니다.

## 준비한 음성 어댑터

`yuldion.adapters.cosyvoice:create_voice`는 다음 작업을 수행합니다.

1. 생성된 `Performance.delivery`를 instruction으로 사용하고 모델 delimiter만 붙임.
2. 선택된 로컬 모델·기준 음성을 첫 요청 시 로딩. 다운로드·학습·runtime patch 없음.
3. `inference_instruct2(..., stream=True, speed=1.0, text_frontend=False)` 호출.
4. mono tensor를 little-endian float32 PCM으로 변환하고 동일 plan ID와 연속 sample offset 부여.
5. 계획된 pause를 발화 끝에 한 번만 추가. 확인되지 않은 breath 요청은 거부.

생성 instruction 뒤에 쉼·호흡을 별도 고정 프리픽스로 강요하지 않습니다. 다만 모델이
자연스럽게 만든 쉼과 수치 pause의 의미가 중복되는지는 실제 청취로 평가해야 합니다.
직접 CosyVoice3 로딩 가능한 전체 모델 디렉터리용입니다. LoRA만 있는 체크포인트,
v16 이후 runtime patches, face-conditioned reference 혼합을 자동 복원하지 않습니다.
전용 private runtime 어댑터가 필요한 경우 이 포트를 대체합니다. CPU/GPU device
선택·dtype 지원은 설치된 CosyVoice 버전에 종속되며 실행 환경을 별도 고정해야 합니다.
취소는 chunk 경계에서 확인하며 모델 내부 blocking 호출을 강제로 종료하지 않습니다.

## 준비한 얼굴 포트

`yuldion.adapters.controlled_face:create_face`는 명시한 별도 패키지의
`backend_factory(options)`를 호출하는 포트입니다. **새 LivePortrait renderer 구현이나
의도→포즈 모델이 완성된 것은 아닙니다.** 기존 GraphFace를 그대로 연결하지 않습니다.

Backend는 `health()`, `render(FaceRequest, cancel)`, `close()`와 아래 capabilities를
제공해야 합니다: `received_audio`, `generated_motor`, `generated_gaze`,
`no_trajectory_replay`. `render`는 현재 PCM, 동일 plan의 motor/gaze 목표와 공통
sample clock을 받아 실제 PNG/JPEG `FaceFrame`을 반환해야 합니다.

각 프레임의 controls에는 다음 receipt를 포함해야 합니다.

- `requested_motor`: 요청한 motor 전체
- `applied_plan_id`: 현재 plan ID
- `trajectory_replayed`: false
- `applied_state`: 보간 후 실제 적용한 표정·시선 제어값의 비어 있지 않은 dict

포트는 plan/clock/순서/receipt를 검사합니다. 이 자기보고만으로 픽셀의 표정 의미나
시선 정확성을 증명하지 않습니다. 실제 렌더 검수가 필요합니다. 이미지/바이트 검사는
엔진에서 추가 수행합니다. 기존 궤적을 재생하는 backend는 지원 대상이 아닙니다.

## 구성과 실행 상태

`examples/model-ports.template.json`은 옵션 문법 예제이며 완전한 장면 설정이 아닙니다.
자신의 Git 제외 장면 설정의 adapters 항목에 복사합니다. 기본 reasoner는 여전히
미연결이며, 이 두 포트가 해석 모델까지 대신 제공하지 않습니다.

얼굴의 `enabled` 기본값은 false입니다. 실제 runtime 구현·모터 좌표계·시선 적용
방식을 검증한 다음 명시적으로 true로 바꿉니다. true에서도 doctor는 설정 문법만
검사한 결과입니다. 실제 backend capability/health 검사는 첫 render에서 수행합니다.
음성 doctor도 로컬 파일·패키지 존재만 확인하며 모델 로딩/품질 보장이 아닙니다.

다음 단계: 학습 담당 작업에서 완료·선택된 모델과 체크포인트 manifest를 확인하고,
격리된 추론 환경에 연결한 뒤 한 문장 생성, 발성·시선 제어 전달과 실제 픽셀/청취를
확인합니다. 본 준비 작업으로 실제 모델 실행·품질 검수·Drive 백업은 수행하지 않았습니다.
