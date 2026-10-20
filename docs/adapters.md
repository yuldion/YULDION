# Model adapter contract v1

`src/yuldion/types.py`가 실제 타입 계약입니다. Python adapter는 별도 설치 패키지에
구현하고 설정의 `entrypoint`를 `installed_module:factory`로 지정합니다. Factory는
`options: dict`를 받아 역할에 맞는 객체를 반환합니다. 엔진은 임의 파일을 검색하거나
플러그인을 설치하지 않습니다. 구성한 플러그인은 사용자가 신뢰하는 Python 코드입니다.

## 공통 수명

- Factory와 `health()`는 모델 다운로드·학습·무거운 로딩을 자동으로 시작하지 않도록
  구현합니다. 실제 추론용 모델 로딩은 첫 작업에서 지연 실행하는 것이 권장됩니다.
- `health()`는 `Health(ready, message, model_id)`를 반환합니다. 경로 존재만으로
  학습·연기 성능이나 GPU 로딩 성공을 보장하지 마세요.
- 모든 작업은 `threading.Event`를 전달받아 취소를 주기적으로 확인해야 합니다.
- `close()`는 해당 어댑터가 소유한 리소스만 해제합니다. 다른 팟·학습 프로세스·모델
  파일을 종료하거나 삭제하지 않습니다.
- 모델별 의존성, GPU dtype, 샘플레이트, 체크포인트 로딩은 어댑터 내부 책임입니다.

## Reasoner

```python
def propose(context: Context, cancel: Event) -> Proposal: ...
def audit(context: Context, proposal: Proposal, cancel: Event) -> Audit: ...
def perform(context: Context, action: Action, view: str,
            action_changed: bool, cancel: Event) -> Performance: ...
```

`Context`에는 불변 장면, 현재 **아직 말하지 않은** 대사, 실제 기록, 지속 행동,
이전 해석, 소비되지 않은 외부 자극 ID, 직전 motor 목표와 기술 피드백이 들어갑니다.
미래 대사는 전달하지 않습니다. `generated_speech`는 합성에 보낸 원문이며 실제
관객이 들은 말이나 그 의미가 확인됐다는 증거가 아닙니다.

첫 제안은 `initialize`이고 현재 script ID를 인용해야 합니다. 이후 `retain` 또는
`change`를 제안합니다. 전환에는 새 자극 또는 새로운 발견의 근거, 이전 가정,
새 통찰, 기존 행동이 부족한 이유가 필요합니다. 감사가 grounded/novel/necessary를
확인해야 엔진이 새 행동 ID를 부여합니다. 구절 변경·쉼·기술 수치만으로 바꾸지 마세요.
감사 모델은 독립 검증자가 아닐 수 있습니다. 의미적 새로움은 엔진이 증명하지 않습니다.

`Action`의 target은 장면 target과 같아야 합니다. 원하는 상대 변화와 전술, 관찰할
검사 기준이 있지만, 실제 성공·실패는 자동 판정하지 않습니다.

`Performance.delivery`와 `motor`는 같은 최종 action/view에서 생성해야 합니다.
엔진은 고정 감정 지시를 덧붙이지 않습니다. 행동을 유지해도 표정·시선·호흡의 세부 표현은 변할 수 있으며, 이전 motor는 연속성을 위한 맥락입니다. 관계 대상과 의도·행동은 유지합니다. motor의 구체적인 좌표와
보간 방식은 선택한 얼굴 어댑터와 합의한 규격입니다. 해부학적 AU 측정값으로 부르지 마세요.

## Voice

```python
def synthesize(request: SpeechRequest, cancel: Event) -> Iterable[AudioChunk]: ...
```

새 음성을 생성해 mono **IEEE float32 little-endian** 바이트를 내보냅니다. chunk의
sample_start는 요청마다 0에서 시작해 연속적이어야 하며, 전체 실행에서 같은
sample_rate를 유지합니다. 모든 chunk에 원래 plan_id를 전달합니다.
계획된 pause/breath 지시는 음성 어댑터가 한 번만 처리합니다. 엔진은 별도 묵음이나
녹음된 숨을 덧붙이지 않습니다. 기본 발성 프리픽스로 생성 지시를 덮어쓰지 마세요.

## Face

```python
def render(request: FaceRequest, cancel: Event) -> Iterable[FaceFrame]: ...
```

같은 plan의 motor 목표와 실제 음성 chunk를 받아 새 프레임을 생성합니다.
`request.global_sample_start`는 공통 오디오 시계입니다. 프레임 sample_start는 그
chunk 범위 안에서 전체 실행 동안 증가해야 합니다. plan_id와 sample_rate가 같아야
합니다. `image`는 PNG/JPEG이고 `controls`에는 실제 적용 상태를 기록합니다.

인물의 정적 외형은 보존하되 과거 표정·시선 궤적을 몰래 재생하지 않는 어댑터를
연결해야 합니다. 프레임마다 새 모델 로드를 하지 말고 상태·렌더러를 재사용하세요.
엔진은 데이터 계약을 검사하지만 픽셀을 보고 표정 의미·닮음·정확한 시선을 검증하지
않습니다. 오디오→정확한 음소 립싱크도 어댑터 능력과 실제 검증에 달려 있습니다.

## 모델 교체

각 역할을 독립적으로 교체할 수 있습니다. 선택한 후보가 나온 뒤 해당 프레임워크
의존성과 체크포인트를 준비하고, 어댑터를 설치한 다음 **로컬 전용 설정 파일**의
entrypoint/options만 변경합니다. 학습 파일은 엔진이 수정하지 않습니다.
연결 확인 → 짧은 실제 생성 → 음성/얼굴/시선 평가를 마친 뒤 정식으로 선택하세요.
테스트 fixture 어댑터는 생산 경로에 포함하지 않습니다.

## 준비된 모델 포트

CosyVoice3 음성 포트와 실시간 motor/gaze 얼굴 backend 연결 포트는
[모델 입출력 조사와 연결 상태](model-ports.md)를 참조하세요. 실제 GPU 연결·품질은
아직 검증하지 않았으며 얼굴 backend 구현은 별도로 필요합니다.

검수된 내장 채팅 경로의 Performance에는 vocal(pace/volume/pitch/articulation/stress)이 추가됩니다. vocal을 검사해 기존 delivery 문자열로 렌더링하므로 음성 어댑터의 기존 instruction 인터페이스는 유지됩니다.

## 음성 지원 능력과 적용 증거

음성 어댑터는 선택적으로 `capabilities()`를 구현합니다.

```python
{
  "schema_version": 1,
  "model_id": "explicit-model-identity",
  "controls": {
    "delivery": {"status": "experimental", "transport": "instruction text", "effect_verified": False},
    "breath": {"status": "unsupported", "transport": "none", "effect_verified": False}
  }
}
```

제어 키는 `delivery`, `pace`, `volume`, `pitch`, `articulation`, `stress`,
`pause_ms`, `breath`입니다. 상태는 `supported`, `experimental`, `unsupported`,
`unknown`입니다. 이는 **전달 기능의 선언**이며 이번 발화의 소리 변화 증거가
아닙니다. 자연어 pitch 지시는 정량적 음높이 제어 지원과 다릅니다.
사전 검사 이벤트 `voice.controls.preflight`에 요청값, 활성 여부, 지원 상태,
선언된 전달 경로를 남깁니다. 활성 미지원 요청은 합성 전에 차단합니다.
`pause_ms=0`, `breath=False`, 빈 강조 목록은 비활성으로 기록합니다.
기존 어댑터가 기능을 선언하지 않으면 `unknown`으로 표시하며, 전달·효과를
자동 확인했다고 기록하지 않습니다. `even`이나 `middle`은 무제어 값이 아닙니다.

`SpeechRequest.control_report`는 선택적인 사전 검사 기록입니다.
합성 요청의 텍스트와 원래 Plan은 수정하지 않습니다. 실제 전달 증거가 있으면
선택 메서드 `control_receipt(request)`가 해당 `plan_id`와 실제 전달값·미지원/
미검증 정보를 반환합니다. 엔진은 합성 완료 후 이를 `voice.controls.receipt`에
저장합니다. 선언만으로 delivered 값이나 effect_verified를 채우지 않습니다.
효과 확인은 나중의 실제 음성 측정·청취 기록으로 별도 증명해야 합니다.

## PCM과 얼굴 처리 분리

CLI `run`의 `--face-mode async`가 기본입니다. 얼굴은 별도 소비자에서
샘플 순서대로 처리하며 음성 생성은 얼굴 렌더링을 기다리지 않습니다.
`--face-mode off`는 얼굴 어댑터를 생성/로드/검사하지 않는 음성 전용 실행입니다.
`sync`는 기존 순차 동작을 비교하는 호환 경로입니다.

앱/재생기는 `Engine.run_streaming(audio_sink, face_enabled=True)`를 사용합니다.
`audio_sink(chunk, global_sample_start, cancel)`가 **얼굴 요청보다 먼저**
원본 PCM을 받습니다. 콜백은 빨리 반환하고 재생기 자체의 큐를 사용해야 합니다.
엔진이 소리를 재생했다고 주장하지 않으며, sink 전달은 스피커 출력 시각이
아닙니다. 실제 예약 시각·버퍼 부족·취소 폐기 구간은 재생기가 기록해야 합니다.

얼굴 큐는 기본 32개 요청으로 제한합니다. 포화 시 새 얼굴 요청만 버리고
`face.request_dropped`에 원인을 남깁니다. PCM을 버리거나 속도를 변경하지 않습니다.
마지막에는 남은 얼굴 처리를 기다려 완료 여부를 확정합니다. 얼굴 실패는
녹음 실패로 숨기지 않고 실행 실패로 남깁니다. 강제로 멈추지 않는 외부
렌더러는 daemon 작업으로 남을 수 있으며, 이 경로가 GPU 프로세스 강제 종료나
완성된 실시간 플레이어를 제공하는 것은 아닙니다.

## 얼굴 지원 능력과 적용 기록

얼굴도 선택적인 `capabilities()`에서 schema_version=1과 controls를 반환합니다.
키는 `expression.brow_inner`, `gaze.target`, `gaze.focus`처럼 motor 사전의
정확한 leaf 경로입니다. 지원 상태·transport·effect_verified 선언 형식은 음성과
같습니다. 넓은 묶음 이름만으로 모든 하위 항목을 지원한다고 추정하지 않습니다.
0이나 False도 명시적인 중립/해제 요청이므로 검사합니다. 활성 미지원 항목은
음성을 합성하기 전에 차단하고, 미선언 항목은 unknown으로 기록합니다.

`FaceRequest.control_report`에 사전 검사 기록을 전달합니다. `face.controls.preflight`
이벤트는 전달/실제 적용/시각 효과를 확인했다고 주장하지 않습니다.
각 프레임의 `FaceFrame.controls`는 `face.controls.receipt`에도 따로 보존하며
backend의 보고라는 범위를 명시합니다. 전용 어댑터에서는 requested_motor,
delivered_motor, applied_plan_id, applied_state, unsupported, experimental,
trajectory_replayed 및 effect_verified를 구분해 남기는 것을 권장합니다.
기존 ControlledFace의 요청·계획·적용 상태 검사 계약은 유지됩니다.

`gaze.target='internal_judge'`는 논리적 주의 대상이지 화면 좌표가 아닙니다.
준비된 명시적 대응 규칙이 없으면 시선 위치를 꾸며내지 말고 제한을 보고합니다.
표정·머리·목·어깨의 실제 지원 여부도 별도 선언이 필요합니다. 공통 샘플 위치는
동기화 기준이며 스피커 출력/디스플레이 표시 시각의 증거는 아닙니다.

발화 전체를 요구하는 얼굴 모델은 capabilities 최상위 `audio_context="utterance"`를
선언합니다(기존 기본은 `chunk`). 엔진은 음성 청크 전달을 계속하고 발화 완료 후
전체 PCM(sample_start=0, 원래 global_sample_start)을 별도 얼굴 큐로 전달합니다.
이는 발화 완료 후 처리이며 온라인/저지연 얼굴 추론이 아닙니다. 얼굴이 오디오와
같이 보이려면 이후 재생기가 명시적인 지연/재생 정책을 정해야 합니다. 전체 PCM은
16 MiB를 넘으면 명시적으로 거부합니다. 임의 조각 추론으로 모델 조건을 바꾸지 않습니다.

`FaceRequest.audio_complete`는 기본 False입니다. 엔진은 전체 발화가 종료된
`audio_context="utterance"` 요청에만 True를 설정합니다. 전체 컨텍스트가 필요한
전용 어댑터는 이 플래그와 audio.sample_start=0을 확인하고, 미완료 청크를
완성 발화라고 간주하지 않아야 합니다.
