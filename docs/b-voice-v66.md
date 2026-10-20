# B 전용 음성 포트 — 로컬 연결 준비, 2026-10-20

상태: 새 어댑터/CPU 계약 테스트/설정 예제만 준비. 실제 런타임을 로드하거나 합성하지
않았다. 현재 학습·체크포인트·GPU·인접 실행 환경을 변경하지 않았다. 아래의 baseline
관측 기록과 이번 코드의 실제 검증 상태를 구분한다. GitHub 공개/Drive 업로드 없음.

## B 식별

B는 별도의 새 학습 체크포인트 이름이 아니라, 사용자가 선택한 음성을 내는 참조 처리와
실행 구성이다. 마지막 보존 경로는 v66 L4이며 v67·v68 후보는 미채택이다.

- `CosyVoice3` base 경로. 로컬 기록상 0.5B 계열이며 upstream release/tag/전체 모델
  디렉터리 revision은 미확정이다. 임의의 최신 CosyVoice3로 대체하면 안 된다.
- 정확한 llm/flow/hift 파일 SHA256과 참조 SHA256은 새 어댑터의 `PROFILE`에 고정했다.
  tokenizer/yaml/부속 ONNX 전체의 해시 집합은 이번 기록만으로 확정하지 않았다.
  이후 실제 복원 시 보완해야 하며, 세 weight hash만으로 전체 환경을 증명하지 않는다.
- 참조 음성 전체의 speaker embedding/LLM 필드와 처음3초의 acoustic context를 사용한다.
  보통 `inference_instruct2(reference.wav)`를 호출하는 포트와 같다고 볼 수 없다.
- 보존 환경: NVIDIA L4, torch2.8.0.dev20250319+cu128, transformers4.51.3, 24kHz mono.
  정확한 baseline 소스 여섯 개의 SHA도 PROFILE에 있다. 소스는 이 포트에 복사하지 않는다.
- native sampler seed5901, speed1.0, FP32 TRT 음향 엔진, fast LM, graph_audio,
  firsthop25와 bridge25/25/50, AMP 피연산자 캐시 및353 prefix graphs를 보존한다.
  graph/cache 한계1024는 유지되며 새로운 긴 입력/긴 지시는 실제 토큰 길이 검사가 필요하다.
- v66에서 같은 조건의 tokens/WAV를 보존한 기록이 있다. v68 RTX4090에서는 tokens와
  길이가 달라지고 새대사 speaker cosine.9401이 기준에 미달했다. 따라서 다른 GPU를
  같은 B로 자동 인정하지 않는다. 이번 새 어댑터 자체의 파형 동등성은 미검증이다.

## 선택과 수명

새 entrypoint: `yuldion.adapters.b_cosyvoice:create_voice`.
`examples/b-voice-v66.template.json`은 voice 항목만의 예제이며 완전한 실행 설정이 아니다.
실제 위치/비밀/가중치/참조/출력은 Git 제외 private 설정에 둔다.

`backend_factory`는 사용자가 명시적으로 설치하고 신뢰한 비공개 inference 패키지의
`module:factory`이다. factory(options)는 이미 준비된 B에 연결하는 backend를 반환한다.
예제의 모듈은 placeholder이며 제공되는 실행 서버가 아니다. 자동 발견/설치/다운로드,
기본 모델로의 대체, 과금 GPU 생성, 학습 환경 import를 하지 않는다.

이미 별도 inference worker에서 v66 구성요소가 준비됐을 때 factory는 다음 facade를
사용할 수 있다. 실제 경로를 넣거나 이 예제를 이번 작업에서 실행하지 않았다.

```python
from yuldion.adapters.b_cosyvoice import PreparedV66Backend, readback_manifest

def create_prepared_b(options):
    ready = your_explicitly_prepared_inference_worker(options)
    manifest = readback_manifest(
        ready.weight_paths, ready.reference_path, ready.runtime_source_paths,
        ready.observed_environment)
    return PreparedV66Backend(ready.voice, ready.engine, ready.lm_candidate,
                              ready.decoder, ready.profiler, manifest)
```

`readback_manifest`는 명시적 setup 단계에서 파일 SHA를 읽고 사적 경로를 결과에서
제외한다. environment는 실제 준비 작업에서 관측해 공급해야 한다. backend의 자기보고와
파일 해시가 GPU 메모리의 텐서·음색·실시간 성능까지 독립 증명하는 것은 아니다.

factory/health/capabilities는 무거운 준비를 시작하지 않는다. BVoice.health의 준비 전
ready는 `factory configured only`이며 backend 연결 완료가 아니다. 첫 synthesize의
attachment에서 manifest와 prepared health를 검사하고 미준비/불일치는 거부한다.
`PreparedV66Backend`는 모델을 구성·patch·warmup하지 않으며 기존 준비 객체만 받는다.
L4 plan/graphs/참조 캐시 준비는 이후 별도로 승인한 inference setup 책임이다.

factory가 제공할 backend API:

- `describe() -> manifest`, `health() -> Health`
- `stream(model_request, cancel) -> iterable[dict]`
- `input_receipt() -> {'request_sha256': digest_of_exact_model_request}`
- `close()`: 해당 연결/facade만 닫음. 학습·팟·공유 모델 종료 금지.

Facade는 engine FP32/LM/bridge/graph_audio를 v66과 같은 순서로 선택하고
`voice.stream(native_request)`의 float PCM을 그대로 전달한다. 모델 객체 공유는 금지한다.
한 inference owner만 허용한다. 취소 시 늦은 PCM은 버리고 native inference를 끝까지
배출해 worker/cache 정리를 기다린다. 따라서 취소/close는 현재 발화 완료까지 막힐 수
있으며 강제 즉시 취소나 GPU 자원 반환을 보장하지 않는다. 동일 plan 자동 재요청도 금지한다.

## 입력과 적용 기록

`SpeechRequest.text`는 원문, `plan.performance.delivery`는 생성 지시다.
새 포트는 기본 대화체/감정 프리픽스를 덧붙이지 않는다. 따라서 원래 baseline 파형을
검사할 때는 원래 지시와 강조를 명시적으로 그대로 입력해야 한다. 새 생성 지시가
기존과 다른데도 같은 WAV를 기대하지 않는다. 음색 보존과 표현 변화는 별도 평가한다.

| 필드 | 상태/실제 전달 |
| --- | --- |
| delivery | supported는 정확한 문자열 전달을 뜻함. 음향 효과 검증은 false |
| pace/volume/pitch/articulation | experimental, 기존 생성 delivery에 포함된 자연어만 전달 |
| stress | experimental, 최대2개 원문 고유 구간을 strong tag로 전달 |
| pause_ms | supported, native 완료 뒤 추가 후행 묵음 한 번. 전체 쉼 길이 아님 |
| breath=true | unsupported, 합성 전 거부. 모델 자연 발생 호흡은 그대로 유지 |

기본 `allow_experimental=false`. 활성 발성 실험은 private 설정에서 명시적으로 true로
선택해야 한다. 전체 vocal을 주면 공통 `vocal_delivery`와 delivery의 일치도 검사한다.
stress만 주는 부분 입력은 baseline 재현 진단용이다. 정상 prepared 경로는 공통 전체
vocal 구조를 따른다. 강세3개/반복 단어/겹치는 구간은 조용히 줄이지 않고 거부한다.
반복 단어의 특정 위치 강세는 향후 span-offset 계약이 필요하다.
숫자 pitch/volume/speed를 적용하거나 gain/pitch/time-stretch로 몰래 대체하지 않는다.
지시의 한글 설명이 영어 발화에서 원하는 결과를 내는지는 이번 CPU 테스트로 알 수 없다.

`capabilities()`와 공통 preflight에 이어 `control_receipt(request)`가 같은 plan ID의
요청값·전달값·status·effect_verified=false를 반환한다. backend가 정확한 model_request
hash를 확인해야 delivery_verified를 기록한다. 값은 실제 Hz/dB/속도가 아닌 전달한
instruction/markup이다. pause는 실제 추가 sample 수를 기록한다. 미요청/미확인 호흡을
적용 성공으로 꾸미지 않는다. 이 영수증은 자기보고이며 청취/음향 평가를 대신하지 않는다.

## PCM와 시계

backend part는 `pcm_f32le:bytes`, `sample_rate:int`, `sample_start:int`를 반환한다.
24kHz mono 유한 float32 little-endian, 요청마다0부터 빈틈 없는 sample offset이다.
포트는 native float bytes를 그대로 내보내며 숫자 편집·재합성·resample을 하지 않는다.
예전 서버의 s16/zlib wire를 이 포트의 f32라고 바꾸어 표기하지 않는다. 그 경로를 쓰려면
명시적 디코딩/양자화 차이 검사가 별도로 필요하다. WAV는 후속 검수 artifact이며 스트림
반환형은 `AudioChunk(plan_id,sample_start,sample_rate,pcm_f32le)`이다.

추가 pause도 같은 sample clock에 포함한다. 샘플 위치는 PCM 내 시간이며 생성 도착시각이나
실제 스피커 재생시각이 아니다. common audio_sink가 받은 시각/예약 재생/언더런/취소를
별도로 기록하고 얼굴은 실제 재생 스케줄 변경을 따라야 한다. 음소 경계는 제공하지 않는다.

## 로컬 검사와 이후 실제 검증

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p test_b_cosyvoice_port.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

모든 새 테스트는 CPU fixture이며 실제 B 합성이 아니다. 이번 작업에서 실행한 실제
모델/청취/지연 시험은 없다. 이후 inference 실행이 승인되면:

1. 전체 모델/소스/참조/환경 readback, 이미 준비한 B 단독 출력의 native float 동등성 검사.
2. 얼굴 없이 짧은 두 발화를 공통 audio_sink에 연결해 plan/PCM/취소/한 번의 추가 pause 확인.
3. 같은 대사에서 발성 한 항목씩 변경해 내용·B음색·강세/조음 효과 청취 및 음향 검사.
4. 실제첫소리/느린회차/끊김과 모델·전송·재생 시간 분리. 최초 준비시간은 별도 표시.

추가 학습 완료를 추정하거나 기존 학습을 재시작하지 않는다. 공통 types/engine/events/
capabilities/streaming 및 기본 cosyvoice.py는 이 전용 포트 작업에서 변경하지 않았다.

이번 로컬 검증 결과: 고유 CPU 테스트18개와 공통 포함 전체115개 통과.
첫 전체 실행은 sandbox의 loopback bind 제한으로 기존 HTTP fixture1개가 실패했고,
외부 API/모델을 사용하지 않는 로컬 테스트 서버 실행 권한으로 재실행해 통과했다.
B baseline 소스 여섯 파일의 실제 SHA와 PROFILE 일치, 예제 JSON 파싱도 확인했다.
가중치/실제 참조 파일을 이번 작업에서 열거나 다운로드하지 않았다.
