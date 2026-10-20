# 전체 분석 → 검수 → 연기 파이프라인

핵심 엔진은 Python 3.11 이상과 표준 라이브러리만 필요합니다. 모델 가중치·개인 음성·얼굴
자료는 포함하지 않습니다. OpenAI는 사용자 API 키와 이용료가 필요하며, 로컬 모델은
사용자가 별도 준비한 서버를 선택합니다. 이 명령들은 학습·다운로드·팟 생성을 하지 않습니다.

```text
prepare: 전체 원문과 주어진 상황 → 원래 분석 순서 → 모든 줄의 뜻·의도·행동 연결
review:  원문/시간 순서/가설·사실/전환 필요성 검사 → 통과 또는 수정 필요
plan:    검수된 score 조회 → perform(발성·표정·시선) → 줄마다 체크포인트
run:     같은 검수된 계획 → 명시적으로 연결한 음성·얼굴 어댑터 → 실제 출력
```

실행 시 대사의 뜻·의도·행동을 다시 만들지 않습니다. `read_text/propose/audit` 모델
호출은 실행 경로에서 사용하지 않고, 준비된 항목의 구조 확인과 `perform`만 수행합니다.
예상하지 못한 외부 자극은 명시적 준비 수정이 필요하다고 중단하며 자동 재분석하지 않습니다.

## 설치와 제공자 선택

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
yuldion pipeline init --provider openai --scene examples/hamlet-soliloquy.json \
  --config private/openai.local.json
# 또는 이미 준비한 로컬 서버 선택
yuldion pipeline init --provider local --scene examples/hamlet-soliloquy.json \
  --config private/local.local.json --endpoint http://127.0.0.1:8080/v1/chat/completions
yuldion pipeline check --config private/openai.local.json
```

check는 구조·키 존재만 검사합니다. 연결이나 모델 추론의 성공을 보장하지 않습니다.
키는 `OPENAI_API_KEY` 환경변수나 실행 시 `--prompt-api-key` 숨김 입력으로 제공합니다.
키 값은 설정·요청 로그·manifest에 저장하지 않습니다. API 키를 채팅에 보내지 마세요.

기존 GGUF와 llama.cpp를 명시적으로 실행하려면 별도 준비된 환경에서:

```bash
yuldion pipeline serve-local --model-path /path/to/existing/model.gguf --context-size 32768
```

기본은 CPU 4 threads, GPU layers 0입니다. context 확대는 메모리를 사용하므로 준비된
환경에 맞게 선택하세요. 자동 다운로드나 학습 GPU 공유는 하지 않습니다. 로컬 제공자는
loopback 주소만 허용하며 원격 서버는 운영자가 SSH 터널로 연결해야 합니다.

## 정상 실행 순서

```bash
yuldion pipeline prepare --config private/openai.local.json --prompt-api-key \
  --output-dir outputs/analysis-01 --bound-config private/prepared.local.json --allow-draft
yuldion pipeline review --config private/prepared.local.json --prompt-api-key \
  --output-dir outputs/review-01 --bound-config private/reviewed.local.json
yuldion pipeline plan --config private/reviewed.local.json --prompt-api-key \
  --output-dir outputs/plans-01
```

prepare는 욕구·목표·관계·상황·장애물 → 유닛 → 상황·자극 → 반응·목표·행동 후보
→ 후보 선별·행위 연결 → 종합표 순서를 재사용하고, 원문 모든 줄의 의미·의도·행동을
연결해 저장합니다. 신체화 시험·사용자 설정 행위·촬영 검증은 미수행으로 남깁니다.
`--allow-draft`는 생성 가설 사용이며 사람의 승인도, 의미 검수 우회도 아닙니다.

줄은 화면과 실행의 추적 단위입니다. 단독 문장으로만 해석하지 않고 전체 문법·유닛
맥락에서 준비합니다. 유닛 경계만으로 행동을 바꾸지 않습니다. retain에서는 의도와
행동을 그대로 이어받고, change에는 현재 원문에 근거한 발견과 기존 행동의 부족함이 필요합니다.

review는 새 해석을 쓰지 않습니다. 원문과 전체 준비 결과를 한 번에 읽고 모든 줄을
검사한 목록과 지적 사항만 반환합니다. 근거 없는 단정·미래 정보 선반영·정당화되지 않은
행동 전환·사실/가설 혼동을 점검합니다. issues가 있으면 `needs_revision`으로 저장하고
연기 설정을 만들지 않습니다. 누락된 검수·실패한 검수도 실행할 수 없습니다.
같은 모델의 검수는 독립적인 예술적 평가나 해석의 객관적 진실을 보장하지 않습니다.

분석과 검수 결과를 각각 SHA-256으로 묶어 연결합니다. 원문·장면·준비 분석·검수 결과가
바뀌면 기존 연결을 거부하며 새 설정에 연결해야 합니다. 기존 미검수 실행 기록은 보존하지만
새 경로에 자동으로 통과시키지 않습니다. v1 분석에는 연결된 score가 없어 새 준비가 필요합니다.

## 수정 필요 결과 처리

검수 지적을 검토해 준비 문서의 해당 가설을 수정한 **새 사본**을 만듭니다. 원문과 완료된
전체 분석을 다시 생성하지 않습니다. 행동을 수정하면 뒤의 retain 항목도 일관되게 고쳐야 합니다.
원문이나 목표/관계까지 바뀌는 경우에는 다른 준비 작업으로 취급합니다.

```bash
yuldion pipeline bind --config private/openai.local.json \
  --preparation private/revised-preparation.json --bound-config private/revised.local.json --allow-draft
yuldion pipeline review --config private/revised.local.json --prompt-api-key \
  --output-dir outputs/review-02 --bound-config private/reviewed-02.local.json
```

수정 전 분석·검수·실패 응답은 덮어쓰지 않습니다. 프로그램이 지적 사항을 몰래 고쳐
통과 처리하거나 사람이 확인했다고 기록하지 않습니다.

## 실패한 단계만 재개

출력 디렉터리는 새로 지정합니다. 이전 파일은 보존하고 입력 해시와 성공한 접두 기록을
검증한 뒤 이어받습니다.

```bash
# 전체 분석 중 실패: 검증된 이전 단계와 줄별 score 재사용
yuldion pipeline prepare --config private/openai.local.json --prompt-api-key \
  --resume-from outputs/analysis-01/preparation.json --output-dir outputs/analysis-retry \
  --bound-config private/prepared-retry.local.json --allow-draft
# 의미 검수 통신/형식 실패: 전체 분석 재호출 없이 검수만 재개
yuldion pipeline review --config private/prepared.local.json --prompt-api-key \
  --resume-from outputs/review-01/review.json --output-dir outputs/review-retry \
  --bound-config private/reviewed-retry.local.json
# 연기 지시 실패: 동일 검수·분석으로 성공한 줄을 복원하고 실패 줄부터 재개
yuldion pipeline plan --config private/reviewed.local.json --prompt-api-key \
  --resume-from outputs/plans-01/result.json --output-dir outputs/plans-retry
```

연기 지시는 성공한 줄마다 `result.json`과 `next_segment`를 저장합니다. 재개 시 이전
의도·행동 ID·해석·motor·발견 상태를 복원하며, 발화나 상대 반응을 관측한 것처럼 만들지 않습니다.
재개 범위·분석/검수/장면 해시가 다르거나 저장된 접두 계획이 바뀌면 거부합니다.
검수의 `needs_revision`은 통신 실패가 아니므로 그대로 재요청하지 않고 먼저 수정해야 합니다.

HTTP 상태 코드·재시도 가능 여부·Retry-After를 보존합니다. 401/403 등은 키/권한 수정을,
429나 일시 서버 장애는 대기 후 해당 단계 재개를 안내합니다. 요청 본문에 든 키나 서버 오류
본문은 오류 메시지에 복사하지 않습니다. 자동 무제한 재시도·제공자 전환은 없습니다.
프로세스가 응답을 저장하기 전에 강제 종료되면 원격 요청의 완료·과금을 확정할 수 없습니다.
이 경우 재요청이 완전히 중복되지 않는다고 보장할 수 없습니다.

## 발성·표정·시선

모델은 vocal의 `pace`, `volume`, `pitch`, `articulation`, `stress`를 반환합니다. 발음
설명에 대사를 그대로 넣거나 강세가 현재 원문에 없는 말을 인용하면 거부합니다. 구조화
컨트롤에서 기존 어댑터용 `Performance.delivery`를 구성하므로 발성 필드가 대사로 대체되지 않습니다.
같은 행동 아래에서도 표정·시선·호흡이 달라질 수 있습니다. 이전 motor는 연속성 맥락이며
동일하게 복사해야 하는 값이 아닙니다. 관계 대상은 유지합니다.

실제 효과는 선택 backend의 컨트롤 규격과 연기 평가로 별도 검증해야 합니다. 자연어 motor는
실제 얼굴 좌표가 아니며, 구조 통과가 자연스러운 움직임을 보장하지 않습니다.

## 관찰 화면

```bash
PYTHONPATH=src python3 -m yuldion.tools.inspector.server \
  --config private/openai.local.json --port 8794
```

http://127.0.0.1:8794 에서 전체 분석/구조 검사/의미 검수/연기 지시/실제 미디어 상태를
따로 표시합니다. 버튼은 현재 상태에 맞게 실패한 분석, 의미 검수, 연기 지시 중 하나만 재개합니다.
완료한 분석이 있으면 재생성하지 않습니다. 검수 지적이 있으면 표시하고 실행을 막습니다.
이전 미검수 계획은 `이전 미검수 기록`으로 구분하며 새 검수된 계획으로 세지 않습니다.

키는 숨김 입력하고 관찰 서버 메모리에 유지하며 자식 프로세스 환경으로 전달합니다. 서버는 loopback 전용이고,
다른 사이트에서 키 없이 실행 요청을 보내지 못하도록 Host/Origin/토큰을 검사합니다.
기본 전체 분석은 최대 160회/900초, 검수는 별도 한 요청, 연기 지시는 전체 대본입니다.
검수 결과 길이를 위해 검수 요청은 기본 최대 출력 토큰 4096(설정 범위 128..8192)을 사용합니다.
서버 창을 닫는 것이 원격 API 실행까지 즉시 취소한다는 뜻은 아닙니다.

## 실제 음성·얼굴 출력과 검증 범위

```bash
yuldion pipeline run --config private/reviewed.local.json --prompt-api-key --max-seconds 300
```

명시적으로 연결한 음성·얼굴 어댑터가 필요합니다. 미연결이면 출력 실행을 막습니다.
prepare/review/plan/관찰 화면은 음성·얼굴 모델을 로드하지 않습니다. 원격 학습 환경을
수정하거나 종료하지 않습니다. 현재 체크포인트 재개는 분석·검수·연기 지시까지이며,
실제 PCM/영상의 중간 프레임 재개는 지원하지 않습니다.

단편 비교용 `interpret --diagnostic-reanalyse`는 별도 진단입니다. 정상 연기 경로에 넣지 않습니다.
공개 예제는 `To be, or not to be`부터 `Be all my sins remember’d`까지 원문을 포함합니다.
원문은 [Project Gutenberg Hamlet](https://www.gutenberg.org/files/1524/1524-0.txt)을 사용했습니다.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

테스트는 테스트 전용 응답을 사용합니다. 실제 모델의 해석·검수 품질, 음성 청취·얼굴 지각 평가,
GitHub 업로드와 Drive 백업은 각각 별도로 확인해야 합니다. 결과는 기본 Git 제외 outputs/private에 저장됩니다.


### 관찰 서버의 키와 형식 오류 재시도

화면에서 한 번 입력한 OpenAI 키는 관찰 서버 프로세스의 메모리에 유지됩니다.
페이지를 새로고침하거나 실행이 완료·실패해도 재입력할 필요가 없습니다.
`키 연결`은 실행 없이 키를 연결하고, `키 지우기`는 다음 실행에 사용할 세션 키를
해제합니다. 서버 재시작 시 다시 입력합니다. 이미 실행 중인 작업의 인증은
해제 버튼으로 취소되지 않습니다. 키는 파일·브라우저 저장소·로그에 저장하지
않으며 상태 응답에는 연결 여부만 포함합니다. 서버 환경변수로 설정한 키는
별도 설정이므로 세션 키 지우기의 대상이 아닙니다.

연기 지시의 JSON 모양·발성 값·멈춤/호흡 형식 오류는 같은 줄에 대해
최대 3회(최초 요청 + 수정 요청 2회) 시도합니다. 거절된 원응답과 오류는
실행 기록에 남기고, 검수된 뜻·의도·행동과 앞서 완료된 줄은 유지합니다.
통신·인증·요금 오류나 의미 검수 지적을 형식 수정으로 덮어쓰지 않습니다.
3회 모두 실패하면 해당 줄에서 멈추며, 연결된 키로 그 줄부터 재개할 수 있습니다.

완료된 연기 지시 뒤로 이어가려면 `pipeline plan --config <reviewed-config> --output-dir <new-directory> --segments 12 --extend-from <completed-result.json>`을 사용합니다. 같은 분석·검수 해시와 연속된 기존 계획을 검증한 뒤 새 줄만 호출합니다. 실패 기록의 `--resume-from`은 기존 범위를 유지하며 재개합니다. 관찰 화면에서는 완료된 접두 계획 다음을 대본 끝까지 이어갑니다.


### 한 번 시작하는 전체 실행과 자동 복구

관찰 서버의 기본 작업은 전체 대본 분석 → 의미 검수 → **대본 끝까지** 연기
지시 생성입니다. 기존에 완료된 분석·검수·계획이 있으면 해시를 확인하여
재사용하며, 7줄/12줄에서 사용자의 재실행을 기다리지 않습니다.
작업 감독자는 복구 가능한 저장 오류 기록을 보고 최대 3개 실행 시도를
관리합니다. 429·일시적인 연결/타임아웃·일부 서버 오류는 지연 후 실패 단계만
재개합니다. 모델 응답 형식 오류는 같은 줄에서 최대 3회 먼저 요청한 뒤,
필요하면 감독자가 저장된 해당 줄부터 재개합니다. 재시도 이력과 원응답은
보존됩니다. 인증 실패·의미 검수 수정 필요·소스 또는 해시 불일치는 자동
복구하지 않습니다. 복구 한도에 도달하면 실패 위치를 남깁니다.
각 작업 시도는 별도 하위 폴더에 저장되고, 상위 job.json이 현재 시도를
가리킵니다. 키는 관찰 서버 메모리에서 하위 작업 환경으로 전달하므로
작업 재개 때 다시 입력하지 않습니다. 관찰 서버 자체를 종료·재시작하면
메모리 키는 사라집니다. 운영체제 강제 종료나 호스트 재부팅의 무인 복원은
이 기능의 범위가 아닙니다.


### 실제 API 장애 복구 검증

관찰 화면의 `실제 API 오류 복구 검증`은 기존 검수된 첫 12줄을 보존하고
13줄부터 끝까지 실제 API를 호출합니다. 18번째 줄에서 실제 응답을 받은 직후
로컬 연결 예외를 정확히 한 번 주입합니다. 해당 응답과 영수증은 별도 파일에
보존하고 계획에는 반영하지 않습니다. 감독자가 18줄부터 자동 재개하며,
화면에는 실제 호출 수·시도별 줄 번호·오류 주입·보존 및 완료 검증을 표시합니다.
외부 OpenAI 서버의 장애를 유발하는 테스트가 아니라 클라이언트가 응답을 받은
직후 연결이 끊긴 상황을 재현하는 테스트입니다. 분석·의미 검수는 재호출하지
않고 음성·얼굴 모델도 로드하지 않습니다. 이 버튼은 새로운 API 사용량을 발생시킵니다.
