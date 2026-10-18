# 단계별 대본 분석

YULDION의 음성·얼굴 실행과 분리된 CLI입니다. 사용자가 정한 행동 동사 분석
순서를 따릅니다. 모델은 한 번에 한 항목만 제안하며, 사람이 명시적으로 확정하기
전에는 다음 항목을 요청할 수 없습니다. 모델 가중치나 고정 햄릿 해설은 포함하지
않습니다. 모델의 실제 의미 해석 능력과 연기 품질은 별도로 검증해야 합니다.

## 설치와 시작

Python 3.11 이상, macOS/Linux. 실행 중 분석 파일 잠금은 POSIX `flock`을 사용합니다.
Windows에서는 WSL을 사용하세요. 런타임은 Python 표준 라이브러리만 사용합니다.

```bash
python -m pip install -e .
mkdir -p private
# 학습·GPU 실행 없이 원문/진행 파일만 준비
yuldion-analyze init --script examples/analysis-hamlet.json --state private/analysis.local.json
yuldion-analyze status --state private/analysis.local.json
```

설치 없이 `PYTHONPATH=src python3 -m yuldion.analysis`로 같은 명령을 실행할 수 있습니다.
`init`은 기존 파일을 덮어쓰지 않습니다. source hash가 바뀌면 기존 분석을 진행하지
않습니다. 새 원문으로 새 분석 파일을 만드세요. 이전 미배포 schema v1 초안은
지원하지 않으며 schema v2를 새로 초기화합니다.

원문의 `relationship_targets`는 분석할 상대를 사람이 명시하는 목록입니다.
독백에서 자기 자신을 대상으로 삼는 것도 해석적 설정임을 표시하세요. 햄릿 공개
예제는 Shakespeare 3막 1장의 퍼블릭 도메인 영어 원문 일부이며, 구두점·줄 배치는
입력 예제의 선택입니다. 현대 번역문이나 편집본의 주석을 포함하지 않습니다.

## 정확한 순서

1. **대본 분석:** 욕구 → 장면 초목표 → 관계(상대별 하나씩) → 시작 시점 주어진 상황 → 초기 갈등·방해 요소.
2. **유닛 구분:** 시작~끝 줄과 구분 이유를 유닛별 하나씩 확인 → 전체 유닛 표 확인. 사고·행동의 변화가 기준이며 이 단계에서 자극을 미리 확정하지 않습니다.
3. **상황·자극:** 유닛 1의 상황 → 마지막 대사·지문의 자극 → 다음 유닛. 자극은 다음 유닛 반응의 계기가 됩니다.
4. **유닛 분석:** 유닛별 정서적 반응 → 상대에게 원하는 변화 → 행동 동사 후보 4~6개. 첫 유닛의 정서는 시작 전 초기 조건입니다. 모든 유닛 완료 후 선별로 넘어갑니다.
5. **행동 동사 선별:** 유닛별 목표 적합성·탈락 이유·순위 → 사용자의 신체화 점검 결과 → 그 결과에 따른 선별 → 대상 작용성·명확성 검토·최종 동사. 모델이 사용자의 신체 경험을 대신 작성하지 못합니다.
6. **행위 구체화:** 유닛별 지문 행위 → 사용자가 설정할 행위 → 행위와 동사 연결 → 순위 조정. 지문에 행위가 없으면 없다고 명시하고 발화·태도의 수행을 검토합니다.
7. **수행 재검증:** 전체 최종 분석표 확인 → 사용자의 장면 수행·촬영 후 관찰 결과 입력·확정. 실제 수행 없이 자동 완료하지 않습니다.

관계별/유닛별 모든 항목은 독립된 확인 대상입니다. 유닛은 첫 줄부터 마지막 줄까지
빠짐·겹침 없이 이어지고, 마지막 줄에 도달해야 다음 단계가 열립니다. 현재는 줄 ID
단위 경계만 지원하므로 한 줄 내부의 전환은 입력 줄을 더 작게 나누어 준비하세요.
최종 표는 모델이 이전 확정 내용을 정리한 제안이며 사용자 확인이 필요합니다.

## 모델 연결과 한 항목 제안

이미 사용자가 준비한 chat-completions 호환 서버를 지정합니다.
`examples/analysis-model.template.json`을 Git 제외 경로에 복사해 실제 모델 ID와
endpoint를 설정하세요. endpoint는 완전한 `/v1/chat/completions` URL이어야 합니다.
템플릿의 모델명은 자리표시자이며 실제 모델이 아닙니다. 로컬 모델 서버도 별도 준비가
필요합니다. 이 프로그램은 모델 설치·다운로드·서버 실행·학습을 하지 않습니다.
API 키는 파일 대신 `api_key_env`가 가리키는 환경변수에 둡니다. 키가 없는 로컬
서버라면 `api_key_env` 항목을 지우세요.

```bash
yuldion-analyze propose --state private/analysis.local.json --model-config private/model.local.json
# 제안과 원문 근거를 읽고 명시적으로 확정
yuldion-analyze review --state private/analysis.local.json --approve
# 또는 거절: 같은 항목에 머무름
yuldion-analyze review --state private/analysis.local.json --reject
```

위 approve/reject는 둘 중 하나만 선택합니다. 수정할 경우 현재 pending의 `proposal`
객체를 JSON 파일로 복사·수정해 `review --approve --edited private/edit.local.json`으로
확정합니다. 원문에 없는 인용문이나 다른 단계로 바꾼 수정은 거부합니다.

모델 서버에는 전체 입력 대본·배경과 이전 확정 분석을 전송합니다. 현재 단계만
생성시키지만 전체 대본을 읽는 **사전 분석**이며, 미래 대사를 숨기는 실시간 배우의
Context와 다릅니다. 외부 서버의 데이터 취급·이용 요금은 사용자가 선택한 서비스에
따릅니다. 기본 상태에서 외부 서버로 자동 연결하지 않습니다. HTTPS 또는 loopback
HTTP만 허용하고, redirect를 따라 인증 헤더를 전송하지 않습니다.
JSON 응답 모드를 지원하는 endpoint가 필요합니다. 잘못된 응답은 자동 수정·확정하지
않으며 현재 단계에 남습니다. JSON으로 읽은 부적합 제안은 history에 보존합니다.
네트워크 오류·JSON 파싱 자체가 실패한 응답 본문은 저장하지 않습니다.

## 모델 없이 검토 흐름 사용하기

현재 단계의 프롬프트를 파일로 저장하고, 자신이 선택한 별도 모델에서 응답을 받아
가져올 수도 있습니다. 이것은 YULDION의 실제 추론 실행으로 기록하지 않습니다.

```bash
yuldion-analyze prompt --state private/analysis.local.json --output private/prompt.local.json
yuldion-analyze propose --state private/analysis.local.json --proposal-file private/proposal.local.json
```

응답 구조:

```json
{
  "task": {"stage":"desire","unit":null,"target":null,"human_input":false,"label":"욕구"},
  "items": [{"claim":"검토할 해석 한 문장", "kind":"interpretation_hypothesis",
    "evidence":[{"line_id":"L01","quote":"To die, to sleep"}]}],
  "data": {}
}
```

이것은 문법 설명용 예제이며 햄릿 분석 완료 결과가 아닙니다. 정확히 현재 `task`와
하나의 item을 반환해야 합니다. `unit` 단계의 data에는 `start_line_id`, `end_line_id`,
`candidates`에는 `verbs` 배열(4~6개)을 넣습니다. 다른 단계의 data는 빈 객체입니다.
사실과 가설은 구분하지만 인용문 존재 검사만으로 주장의 타당성을 증명하지 않습니다.
탈락 이유·순위·감정 동사 여부·관계의 타당성은 사람의 검토가 필요합니다.

## 사용자 입력·되돌아가기·내보내기

신체화 점검/사용자 행위/최종 수행 검토 단계에서는 `propose`가 차단됩니다.
자신의 관찰을 텍스트 파일에 적어 제출한 뒤, 그 입력도 별도로 확인·확정합니다.

```bash
yuldion-analyze input --state private/analysis.local.json --text-file private/observation.txt
yuldion-analyze review --state private/analysis.local.json --approve
# status/export에서 확인한 0부터 시작하는 기존 확정 인덱스로 돌아가기
yuldion-analyze rewind --state private/analysis.local.json --index 2
yuldion-analyze export --state private/analysis.local.json --output private/analysis.md
```

되돌리기는 해당 항목부터 이후 확정을 무효화하고 원래 기록은 history에 보존합니다.
변경된 목표·관계·유닛에 이전 결론을 몰래 재사용하지 않습니다. 잠금으로 동일 파일의
동시 CLI 변경을 막고, 파일 교체로 저장합니다. Git 제외 `private/`에 보관하세요.
상태 JSON에는 원문·제안·수정·확정·모델 사용량·프롬프트 hash가 들어갑니다. Markdown은
확정된 항목만 출력하고, 미완료 분석은 미완료로 표시합니다. 실제 인간 본인 여부를
인증하는 시스템은 아니며, JSON 편집에 대한 보안 감사 장부도 아닙니다.

## 이번 구현의 검증 범위

모델 대신 테스트 전용 응답을 사용해 다중 유닛 전체 순서, 확정 전 진행 차단,
거절·수정·되돌리기, 사용자 입력 단계, 원문 인용 검사, CLI 저장·내보내기와 네트워크
요청 형식을 검증했습니다. 실제 언어모델·GPU는 실행하지 않았습니다. 실모델 연결 시
햄릿 한 항목부터 생성해 근거·목표·행동 후보를 사용자가 검수해야 합니다.
음성/얼굴 엔진에 분석을 자동 적용하는 기능과 화면 UI는 이번 범위에 없습니다.
