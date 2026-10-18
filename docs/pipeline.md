# OpenAI / 로컬 모델 선택 파이프라인

YULDION은 독립 AI 배우 엔진입니다. 해석 제공자를 바꾸어도 같은 대본·상황,
원문 근거 검사와 실행 기록 형식을 사용합니다. 행동동사 분석 CLI는 별도 선택 도구이며
이 파이프라인의 필수 단계가 아닙니다.

```text
설치 → 제공자 선택/init → 설정 검사/check
  ├─ interpret: 첫 대사 → 전체 구절 읽기/구절 관계 → 해석·의도 → 근거 감사 → JSON 기록
  └─ run: 같은 해석 어댑터 → 행동 유지/전환 → 발성/motor 지시 → 음성 → 얼굴 → 실행 기록
```

**현재 바로 시험할 수 있는 범위는 해석 전용 경로입니다.** 전체 배우 실행에는 별도로
준비한 음성·얼굴 어댑터가 필요합니다. 설치만으로 학습 중인 모델에 연결하지 않습니다.

## 1. 설치

Python 3.11 이상. 핵심 엔진과 CLI는 Python 표준 라이브러리만 사용합니다.

```bash
git clone https://github.com/yuldion/YULDION.git
cd YULDION
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
yuldion pipeline --help
```

Windows PowerShell의 가상환경 활성화는 `.venv\Scripts\Activate.ps1`입니다.
배우 엔진/파이프라인은 플랫폼 중립 Python이며, 선택 행동동사 도구의 파일 잠금은
macOS/Linux(Windows는 WSL) 기준입니다. 로컬 모델 실행기는 OS에 맞게 별도 설치합니다.
`yuldion-pipeline`과 `python -m yuldion.pipeline`도 같은 하위 명령을 제공합니다.

## 2A. OpenAI 선택

```bash
yuldion pipeline init --provider openai --model gpt-4.1 \
  --scene examples/hamlet.json --config private/openai.local.json
# 통신 없이 설정·키 존재만 검사
yuldion pipeline check --config private/openai.local.json
```

키가 없으면 check 종료 코드 2가 정상입니다. 키 값을 설정 파일에 넣지 마세요.
실행 시 아래처럼 숨김 입력을 사용할 수 있습니다. 키는 이번 프로세스에서만 사용하고
설정·로그·결과 파일에 저장하지 않습니다.

```bash
yuldion pipeline interpret --config private/openai.local.json --prompt-api-key
```

이미 `OPENAI_API_KEY` 환경변수를 설정한 환경에서는 `--prompt-api-key` 없이 실행합니다.
`init --api-key-env MY_KEY_ENV`로 다른 환경변수 이름을 선택할 수 있습니다.
`--model`은 사용 가능한 API 모델 ID이며 기본 예제는 `gpt-4.1`입니다. 임의의 모델이
현재 전송 매개변수(`temperature`, `max_tokens`, Chat Completions)를 모두 지원한다고
보장하지 않습니다. 다른 모델은 호환성을 확인하세요.

OpenAI 모드는 공식 `https://api.openai.com/v1/chat/completions`만 사용합니다.
대본과 생성된 분석을 외부 API에 전송하며 사용자의 API 계정에 비용이 발생합니다.
프로그램 소스의 MIT 공개와 API/모델 이용 조건·과금은 별개입니다.
이 저장소가 공용 API 키나 무료 API 사용권을 제공하지 않습니다.

[공식 OpenAI 구조화 응답 문서](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)에
맞춰 JSON 모드를 사용합니다. 로컬 tuple JSON Schema를 OpenAI에 그대로 보내지 않습니다.
JSON 모드는 구체적 스키마나 해석 타당성을 보장하지 않으므로 동일 Python 검사를
별도로 적용하며 실패 시 다른 제공자로 자동 전환하거나 응답을 고쳐 채택하지 않습니다.

## 2B. 로컬 Qwen + llama.cpp 선택

로컬 해석은 유료 외부 모델 API 없이 직접 실행합니다. 장비/서버 비용과 모델
라이선스는 별개입니다. 이 프로젝트가 llama.cpp 또는 모델 가중치를 포함하지 않습니다.

1. [llama.cpp 공식 배포](https://github.com/ggml-org/llama.cpp/releases)에서 OS/CPU에 맞는
   실행기를 설치하거나 [공식 빌드 안내](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)를 따릅니다.
2. [Qwen 공식 GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF)에서 `Qwen3-8B-Q4_K_M.gguf`를
   선택해 모델 보관 위치에 받습니다. 약 5GB의 모델 파일과 추가 실행 메모리가 필요합니다.
   용량·버전·SHA-256과 사용 모델의 라이선스를 확인하세요. 큰 모델과 GPU 환경은
   준비된 RunPod 영구 스토리지를 우선 사용하고 학습 작업과 자원을 분리하세요.
3. **이번 추론을 위해 따로 준비한 환경**에서 명시적으로 서버를 시작합니다.

```bash
# 첫 터미널: 기존 GGUF만 로딩. 다운로드/학습/팟 생성 없음.
yuldion pipeline serve-local --model-path /workspace/models/Qwen3-8B-Q4_K_M.gguf \
  --model-id yuldion-qwen3-8b --port 8080
```

`llama-server`가 PATH에 없으면 `--binary /path/to/llama-server`를 지정합니다.
기본값은 CPU 4 threads, GPU layer 0, context 4096, slot 1입니다.
전용 GPU 또는 Apple Metal 환경에서 GPU를 사용하려면 `--gpu-layers 99`를 명시합니다.
학습 중인 GPU에 자동으로 얹지 않습니다. 서버는 전경에서 실행하며 종료는 해당
터미널의 Ctrl+C로 합니다. 다른 작업의 모델/프로세스를 종료하거나 정리하지 않습니다.

실제 해석에 사용한 실행기 버전은 **llama.cpp b11718**입니다. `--reasoning off`, Jinja,
chat-completions와 tuple schema 지원이 필요한 경로입니다. 다른 버전은 호환성을
검사해야 합니다. 일부 local compatible 서버는 strict schema가 다를 수 있습니다.

```bash
# 두 번째 터미널: 같은 가상환경을 활성화한 후
yuldion pipeline init --provider local --model yuldion-qwen3-8b \
  --endpoint http://127.0.0.1:8080/v1/chat/completions \
  --scene examples/hamlet.json --config private/local.local.json
yuldion pipeline check --config private/local.local.json
yuldion pipeline interpret --config private/local.local.json
```

로컬 모드는 loopback HTTP 주소만 허용하고 외부 API 키를 붙이지 않습니다.
환경변수의 HTTP proxy도 이 모드에서는 사용하지 않습니다. RunPod 내부에서는
서버와 YULDION을 같은 준비된 추론 환경에서 실행하면 됩니다. 다른 컴퓨터에서
접속하려면 SSH 터널을 사용합니다. 예를 들어 이미 접속 가능한 서버에 대해:

```bash
ssh -N -L 8080:127.0.0.1:8080 your-prepared-inference-host
```

위 호스트는 자리표시자이며 기존 학습 서버를 자동 선택하지 않습니다. 인증 없는
모델 서버를 공용 인터넷에 노출하지 않습니다. 모델 다운로드/서버 실행은 자동
시작되지 않으며, `init`/`check`는 GPU·네트워크 추론을 호출하지 않습니다.

## 3. 같은 입력으로 두 모드 비교

각 제공자로 만든 설정의 scene/script가 같으면 `interpret`가 같은 첫 대사를 보냅니다.
각 실행은 새로운 출력 디렉터리를 만들므로 서로 덮어쓰지 않습니다.
명시한 결과 위치도 이미 존재하면 거부합니다.

```bash
yuldion pipeline interpret --config private/openai.local.json --prompt-api-key \
  --output-dir outputs/openai-first-line
yuldion pipeline interpret --config private/local.local.json \
  --output-dir outputs/local-first-line
```

각 디렉터리에는 다음이 생깁니다.

- `input.json`: 첫 대사, 장면 설정, 비밀값 없는 제공자 옵션.
- `result.json`: 원문 읽기, 앞뒤 구절 관계, 해석·의도·근거, 감사, 실제 모델 요청·응답·사용량·시간.
- `manifest.json`: 실행 ID, 제공자/요청 모델/응답 모델, 코드 commit(소스 checkout인 경우),
  실행 소스 SHA-256, 입력·결과 SHA-256, 성공/실패·미채택·백업 미검증 상태.

실제 모델 가중치 SHA는 HTTP 응답만으로 확인할 수 없어 `not_supplied`로 기록합니다.
로컬 모델의 별도 보관 manifest에 정확한 가중치 SHA와 런타임 버전을 연결하세요.
코드 hash는 설치 패키지에서도 기록하므로 Git이 없어도 실행 코드 비교가 가능합니다.
출력은 대본과 사적 해석을 포함하므로 기본 `outputs/`와 `private/`를 Git에서 제외합니다.

종료 코드 0은 생성·검사가 끝난 상태이며, 2는 설정/키/통신/출력 형식/근거 검사의
실패 또는 grounded=false입니다. 실패 시 상태와 수신된 응답을 보존하며 채택본으로
가짜 대체하지 않습니다. 네트워크 또는 JSON 파싱 전에 실패한 응답 본문은 보존하지
않습니다. 사용자 중단은 130입니다. 같은 모델 감사는 독립 검증이 아니며 성공 코드가
정답·연기 품질·사용자 채택·실제 장치 재생을 보장하지 않습니다.

`check` 성공은 설정·키 존재 검사만 통과했다는 뜻입니다. 연결이나 모델 로딩은
검사하지 않습니다. `interpret`는 **첫 대사만**, 음성·얼굴 로드 없이 실행합니다.
준비된 장면 목표와 관계는 리허설 가설이며 자동으로 사용자 확정 분석이 되지 않습니다.

## 4. 음성·얼굴이 준비되면 전체 배우 실행

같은 private 설정의 `adapters.voice`와 `adapters.face`를
[모델 포트 규격](model-ports.md)에 맞는 별도 설치 어댑터로 연결합니다.
모델 선택은 실행 사이에 설정을 바꾸는 방식이며 학습 파일을 수정하지 않습니다.

```bash
yuldion pipeline run --config private/local.local.json --max-seconds 300
# OpenAI 설정을 선택한 경우
yuldion pipeline run --config private/openai.local.json --prompt-api-key --max-seconds 300
```

전체 실행은 기존 엔진의 행동 유지/전환, 공통 오디오 시계, PCM/얼굴 출력 계약을
사용합니다. 음성·얼굴이 미연결이면 추론 전에 실패하며 fake output으로 진행하지
않습니다. 현재 실제 모델 3종을 연결한 전체 실행과 연기 품질은 검증되지 않았습니다.
얼굴 포트에는 새로운 해석·의도를 실제 표정·시선 좌표로 바꾸는 backend가 필요합니다.
연기 지시의 motor 좌표계도 해당 backend와 합의해야 합니다.

## 테스트와 검증 상태

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

테스트는 제공자 선택, 외부 전송 경계, 키 부재, 실제 loopback HTTP 연결(테스트 전용
응답), OpenAI 요청 형식(mock), 원문 근거·관계·의도 검사, 실패 보존, 중복 출력 방지를
검증합니다. loopback socket 생성을 허용하는 환경에서 실행해야 합니다.
Qwen3-8B Q4_K_M + llama.cpp b11718의 실제 첫 대사/전체 구절 읽기는 별도로 실행해
확인했습니다. OpenAI는 API 키가 없어 실제 계정 호출을 수행하지 않았습니다.
GitHub 코드 업로드, 모델 실행, 사용자 채택, Drive 백업은 각각 별개 상태입니다.

## 독백 전체를 읽고 특정 구절 해석하기

```bash
yuldion pipeline init --provider openai --scene examples/hamlet-soliloquy.json \
  --config private/openai-soliloquy.local.json
yuldion pipeline interpret --config private/openai-soliloquy.local.json \
  --context full-script --focus-index 1 --prompt-api-key
```

`--context full-script`는 설정의 script 전체를 준비 맥락으로 모델에게 전달합니다.
`--focus-index 1`은 그중 두 번째 입력 구간을 현재 해석 대상으로 지정합니다.
이 예제는 To be, or not to be부터 Be all my sins remember’d까지 독백 35줄 전체를
포함하고, 현재 대상은 원문 판본의 `To die—to sleep,\nNo more`입니다. 이전 입력의
쉼표·대시는 판본과 달랐으며 여기서는 아래 출처의 구두점을 유지합니다.
입력 배열 3조각은 대상 구절을 지정하기 위한 텍스트 분할이며 심리적 유닛 확정이 아닙니다.

전체 대본은 배우/리허설의 준비 정보이고, 뒤 대사의 발견이 현재 인물에게 이미
일어난 사건은 아닙니다. 모델 프롬프트와 결과 기록에서 준비 맥락과 현재 대사를
구분합니다. 이 구분의 실제 연기 타당성은 검수가 필요합니다.
기본 `--context current-line`은 여전히 선택 구간만 보내는 비교용 경로입니다.
이 옵션은 해석 전용 interpret/probe에 적용하며 전체 배우 run에 준비 대본을
자동 주입하는 기능은 아닙니다.

공개 원문: William Shakespeare, Hamlet, Act III Scene I,
[Project Gutenberg ebook 1524](https://www.gutenberg.org/files/1524/1524-0.txt).
`examples/hamlet-soliloquy.txt`는 해당 독백 원문이고, JSON은 그 원문을 입력용으로
분할한 파일입니다. 현대 번역이나 편집자의 해설은 포함하지 않습니다.

숨김 키 입력부터 위 독백 실행까지 한 번에 시작하려면 저장소 루트에서:

```bash
bash scripts/run_openai_soliloquy.sh
```

이 스크립트는 별도 키 파일을 만들지 않습니다. 기존 private 설정은 덮어쓰지 않으며,
환경변수 키가 없을 때만 숨김 입력을 요청합니다. `YULDION_PYTHON`으로 Python 실행기를
선택할 수 있습니다. 이 Mac에서 기본 Python CA 연결이 실패하는 문제는
`SSL_CERT_FILE=/etc/ssl/cert.pem`으로 확인했으며, 스크립트는 별도 CA 설정이 없고
시스템 CA 파일이 있을 때만 이를 사용합니다. TLS 검증을 끄지 않습니다.
API 키가 설정되지 않은 현재 단계에서는 생성 결과가 아직 없습니다. 터미널에서 실행하면
실제 OpenAI 호출 후 `outputs/interpret-.../result.json`에 해석·의도를 보존합니다.
