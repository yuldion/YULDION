# Hamlet B / v10 / v30 / v36 얼굴 포트 준비

2026-10-20. **로컬 계약 구현이며 실제 얼굴 연결·GPU·시각 효과 검증은 미실행**.
`yuldion.adapters.hamlet_face:create_face`만 추가했다. 학습 코드, 체크포인트,
공통 엔진/types/streaming/ControlledFace, 모델 선택 상태를 변경하지 않는다.
실제 backend는 별도 추론 환경에서 준비해야 한다. 이 문서와 CPU fixture는
완성된 얼굴 모델이나 실시간 송출 결과가 아니다.

## 확인한 기존 모델과 출력

| 구성 | 확인한 역할 | 현재 제한 |
|---|---|---|
| MuseTalk V1.5 UNet + SD VAE + Whisper | 실제 PCM에서 하관을 만들고 LP 표현 잔차 `(21,3)` 추출 | 기존 공식 B 경로. 후속 미채택 입 보정·v39를 자동 사용하지 않음 |
| LivePortrait | 현재 입/표정 잔차와 머리 회전을 합쳐 RGB 얼굴 생성 | 해부학적 AU/근육 모델이 아님 |
| v10 시선 | 공통 3D 주시점, 눈 모서리 추적, 사진 눈 텍스처 | 고정 카메라·작은 회전. **선택된 v09 existing compositor** 사용 |
| v09 목·어깨 | 현재 머리 운동에서 몸 GRU/관절 어댑터와 연결 리그 구동 | 저장된 관절 궤적 재생을 연결로 인정하지 않음. 독립 어깨 연기 제어 미지원 |
| v30 + v29 | 전체 발화 PCM → 안쪽 눈썹/미간 → 보정된 표면 전달 | 양방향 GRU·발화 전체 정규화. 현재 chunk-only 스트리밍 불가 |
| v36 | 머리 기준 위치와 턱·목 연결 안정화 | 작은 회전 범위. 볼·턱 울렁임 해결/실시간 보장은 없음 |

기존 연구의 내부 출력은 512×512 RGB, 25fps다. 엔진 전달용 backend 출력은
512×512 PNG bytes로 한정한다. 다른 실험의 MP4나 고정 표정·고개·시선 궤적을
프레임 공급원으로 쓰지 않는다. 정적인 인물·리그·보정 자산만 명시적으로 재사용한다.
v39 시험 경로에는 별도 `TemporalIris` 클래스가 있었지만, 그것을 선택된 v10
합성 방식과 동일하다고 간주하지 않는다. manifest로 `v09_existing`을 구분한다.

읽기 근거는 연구 코드의 `speech_portrait_v02/teacher.py`,
`portrait_motion_v01/renderer.py`, `hamlet_gaze_temporal_v10/README.md`,
`hamlet_joint_learning_v09/{model,rig}.py`, `hamlet_audio_brow_v30/{model,features}.py`,
`hamlet_brow_transport_learning_v29/surface.py`, `hamlet_motion_stability_v36/stabilizer.py`다.
실제 실행 시 버전별 소스·자산의 SHA를 사적 manifest로 고정해야 한다.

## 공통 계약과 필요한 변경 제안

`FaceRequest(plan,audio,global_sample_start[,control_report,audio_complete])` 및
`FaceFrame(plan_id,sample_start,sample_rate,image,format,controls)`를 그대로 사용한다.
`capabilities()`도 공통 schema_version 1 / model_id / dotted motor leaf별 controls를
따른다. 0과 False도 요청이다. 지원하지 않는 요청을 조용히 무시하지 않는다.

공통 담당이 추가한 **audio_context="utterance" / audio_complete=True** 규격에 맞췄다.
이 어댑터는 capabilities 최상위에 `audio_context="utterance"`를 선언한다.

1. 음성 PCM sink는 기존대로 청크마다 즉시 받는다.
2. Engine은 발화 종료 후 전체 PCM을 하나의 AudioChunk(sample_start=0)로 모은다.
3. 원래 global_sample_start를 유지한 FaceRequest(audio_complete=True)를 얼굴 큐에 보낸다.
4. 어댑터가 해당 요청을 받으면 완성 컨텍스트를 내부 등록하고 현재 motor와 함께 전달한다.
   **별도 외부 선등록은 필요 없다.**

whole-utterance PCM은 16MiB 이내다. 완료 표시는 엔진/호출자의 명시적 선언이지
모델이 음성 내용에서 추측한 종료가 아니다. 아직 끝나지 않은 chunk를 완성 발화로
간주하지 않으며 v30을 chunk마다 재실행하지 않는다. 이 경로는 지연된 얼굴 생성이지
실시간 v30이 아니다. 샘플 시계가 맞아도 소리가 먼저 재생되어 얼굴이 늦을 수 있다.
실제 플레이어의 동기화/버퍼 정책이 별도로 필요하다.

`declare_utterance(...)`는 명시적 offline 호출자가 전체 PCM을 먼저 등록하고
그 안의 구간을 검사할 때만 쓰는 선택 API다. 현재 엔진 통합에는 필요하지 않다.
진짜 causal v30 교체는 다른 모델 작업이며 이번 포트가 수행하지 않는다.

## 구체적인 motor 규격

```json
{
  "head": {"pitch_deg": 0, "yaw_deg": 4, "roll_deg": 0},
  "gaze": {"target": "partner"},
  "expression": {"brow_inner": 0.004, "glabella": -0.002}
}
```

| 정확한 경로 | 전달값/범위 | 선언 |
|---|---|---|
| head.pitch_deg / head.roll_deg | −3..3°, 현재 LP 작은 회전 규약 | experimental |
| head.yaw_deg | −6..6°, 양수는 화면 왼쪽 회전 | experimental |
| gaze.target | 설정에 있는 의미 대상 → 명시적 공통 주시점 | mapping 있을 때 experimental, 없으면 unsupported |
| gaze.target_m | `[X,Y,Z]`, 미터; X 화면 오른쪽, Y 위, Z 고정 카메라 쪽 | experimental |
| expression.brow_inner / expression.glabella | −0.025..0.025, v29/v30 기하 명령의 추가 잔차 | experimental |
| gaze.focus / gaze.hold / gaze.blink | 기존 모델에 정확한 변환 규약 없음 | unsupported |
| smile / jaw_open / AU / 독립 목·어깨 제어 | 구체적 지원 경로 및 검증 없음 | unsupported |

`internal_judge` 같은 정신적 대상은 위치가 아니다. 사용자가 정한 위치 mapping이
없으면 거부한다. 자동 카메라 응시·임의 좌표·목표 범위 축소를 하지 않는다.
`gaze.target`과 `gaze.target_m`은 동시에 쓰지 않는다. 현재 포트의 좌표 검사는 유한성/
양의 Z뿐이다. 준비된 backend는 실제 리그로 거리·안구 각도·가림을 검사하고 범위 밖이면
거부해야 한다. 수학적 주시점 일치와 실제 픽셀의 양안 일치는 별도 검증이다.

눈썹 추가 잔차는 **새로 제안한 전달 계약**이다. 아직 시각적으로 검증되지 않았다.
backend는 v30 오디오 예측과 요청 잔차를 분리 기록하고 합성하며, 범위를 넘으면
거부한다. 조용히 clipping하거나 원래 v30 출력을 대체하지 않는다. 요청하지 않은
제어는 현재 상태를 유지한다. 새로운 감정 기본값·저장된 동작 표를 넣지 않는다.
새 목표를 향한 실제 보간 상태는 backend가 보고해야 하며 포트가 요청값으로 꾸미지 않는다.

## 준비된 backend와 무거운 작업의 경계

설정의 `backend_factory: installed_private_package:create_prepared_face`는 명시적으로
준비된 핸들만 붙인다. `health()`나 constructor/manifest 검사에서 패키지 import,
모델 로딩, 파일 탐색, 다운로드, 런타임 설치, 팟 실행을 하지 않는다.
runtime 준비는 이 작업 범위 밖이다. `enabled` 기본값은 false다.

필요 메서드:

- `describe()` → PROFILE 필드, `components_sha256`, `asset_verification="sha256_readback"`.
- `health()` → 별도로 준비된 핸들의 준비 상태.
- `render_packet(packet,cancel)` → PNG·sample_start·request_sha256·실제 applied_state.
- `input_receipt()` → 실제 받은 packet hash, trajectory_replayed=false, temporal_state_reset.
- `close()` → 해당 핸들 해제만. 다른 프로세스·학습·팟·파일을 종료/삭제하지 않음.

`components_sha256`의 10개 논리 항목은 코드의 COMPONENTS에 고정되어 있다.
각 digest는 정확한 자산/소스 bundle의 private manifest를 SHA-256 readback한
값으로 채운다. 테스트용 `a…a`나 임의 값으로 실제 모델 준비를 통과시켜서는 안 된다.
포트는 설정과 backend 보고의 일치를 검사하며, 이 자체가 무거운 모델 파일을
읽었거나 그 가중치를 실제 렌더링에 썼다는 독립 증거는 아니다.

packet에는 현재 PCM 원문, 완성 발화 PCM, 각 해시, 원래 sample rate,
chunk의 상대/전체 sample_start, 현재 motor, 물리 좌표로 바꾼 delivered_motor,
25fps frame sample 목록, 상태 초기화/누락 정보가 들어간다.
backend가 모델용 16kHz로 변환할 수는 있지만, 반환 sample_start/sample_rate는
엔진의 원래 PCM 시계를 유지해야 한다. 원본 PCM을 변경하거나 외부 전송하지 않는다.

## 시계·취소·누락·증거

- 프레임 위치는 전체 시계에서 `floor(k * original_sample_rate / 25)`.
  chunk마다 프레임 시계를 다시 시작하지 않는다. chunk 사이의 누적 반올림도 없다.
- 큐가 버린 얼굴 요청의 PCM은 이미 오디오 경로에 있다. 포트는 다음 요청의
  sample gap을 보고 backend에 시간 상태 초기화를 요구한다. 누락 시각 프레임을
  소급 생성하거나 프레임 시각을 앞당겨서 채우지 않는다.
- 발화마다 v30 오디오 컨텍스트는 갱신하지만, 연속된 발화 사이의 눈/관절 시각 상태를
  무조건 초기화하지 않는다. 현재 샘플 시계가 이어지면 기존 상태를 이어받는다.
- backend가 자체적으로 프레임을 누락시키면 현재 버전은 오류 처리한다. 엔진의
  요청 누락 기록과 별도다. 프레임 없는 매우 짧은 chunk는 정상일 수 있다.
- 취소는 import 전, 각 backend yield 후, 완료 시 검사한다. 자기 iterator만 닫는다.
  블로킹 GPU 커널을 강제 중단하거나 다른 학습을 멈추지 않는다.
- 한 inference/context owner만 허용한다. 오류로 중간 상태가 불명확하면 새 인스턴스가
  필요하며 자동 replay/retry를 하지 않는다.
- `FaceFrame.controls`는 requested_motor / delivered_motor / applied_plan_id /
  실제 backend applied_state / trajectory_replayed=false / unsupported /
  experimental / effect_verified=false를 담는다. 전달 hash 확인과 적용 자기보고를
  픽셀 효과 검증으로 올리지 않는다.
- sample_start는 **스피커가 소리를 낸 시각도, 화면 표시 시각도 아니다**.
  실제 장치의 재생·표시 timestamp와 지연 측정은 후속 실행에서 별도 수집한다.
- PNG 확인은 크기/헤더 수준이다. 전체 이미지 디코딩·외형·입 싱크·동공·울렁임 검수는
  이번 CPU 테스트에 포함되지 않는다.

## 이번 검증과 남은 일

전용 테스트는 가짜 hash와 검은 PNG를 쓰는 CPU fixture다. 실제 모델/렌더 경로에는
fixture를 제공하지 않는다. 현재 motor 변경 전달, 원본 PCM 일치, 시계, 누락, 취소,
표정 미지원, 정신적 주시 대상 거부, 프로필 불일치, 적용 보고 누락을 검사한다.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_hamlet_face_port.py' -v
```

발화 완료 공통 계약과 전용 포트 연결은 로컬 코드에서 맞췄다.
후속 순서: 별도 추론 backend 준비/자산 hash 확인 →
현재 입력으로 한 문장 렌더 → 전달/적용 보고와 실제 픽셀 비교 → 시선·입 싱크·목/어깨·
프레임 시간 평가. 현재는 계약과 CPU 구현만 준비했으며 공개 업로드,
Drive 전달, 원격 실행, 학습 변경은 수행하지 않았다.

2026-10-20 로컬 검증: 전용 테스트 18개를 포함해 현재 전체 CPU 테스트 **139개 통과**.
공통 Engine.run_streaming → 이 포트 → CPU fixture 통합에서도 외부 선등록 없이
완성 발화 PCM·현재 motor·원래 sample_start 전달을 확인했다. sandbox에서는 기존
loopback HTTP 테스트 한 개가 bind 권한으로 실패했고, 로컬 loopback 허용 환경에서
전체를 다시 실행해 통과했다. 테스트 총수는 이 시점의 공통 코드 변경을 포함한다.
새 전용 파일 3개의 공백 검사도 통과했다. 테스트 중 실제 모델·GPU·학습·원격 환경을
실행하거나 변경하지 않았다. 소스는 로컬 추가 상태이며 GitHub/Drive에 게시하지 않았다.
