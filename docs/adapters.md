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
엔진은 고정 감정 지시를 덧붙이지 않습니다. 행동을 유지하면 motor 목표도 정확히
유지해야 하며, 새 구절의 발음은 같은 행동 아래 준비합니다. motor의 구체적인 좌표와
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
