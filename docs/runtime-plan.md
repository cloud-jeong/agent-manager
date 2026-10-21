# Agent 실행 환경 (Runtime) 설계

## Context
지금까지는 agent의 정보(이름, system prompt, 공개 범위, 라벨)만 관리했다. 여기에 등록된 agent를 실제로 실행하는 환경을 추가한다.

### 범위
1. **대화형 채팅**: UI에서 agent를 골라 대화한다. 응답은 스트리밍으로 받고 대화 기록은 DB에 저장한다.
2. **도구 호출**: agent가 도구를 호출하는 agentic loop를 돌린다.
   - 내장 도구: bash, 파일 편집
   - Anthropic 서버 도구: web search, web fetch
   - 원격 MCP 서버
3. **비동기 실행**: API로 입력을 넣으면 백그라운드에서 실행하고, 상태와 결과를 나중에 조회한다.
4. **격리된 샌드박스**: bash와 파일 편집은 대화마다 하나씩 띄우는 Docker 컨테이너 안에서만 실행한다.

### 정해진 것
- LLM은 Anthropic만 쓴다. Python `anthropic` SDK의 async client를 사용한다.
- 기본 모델은 `claude-opus-5-5`이고, agent마다 바꿀 수 있다.
- API 키는 서버 환경변수 `ANTHROPIC_API_KEY` 하나를 모두가 같이 쓴다.

### 제외
- 다른 LLM provider
- 사용자별 API 키
- 사용량 과금과 quota
- 로컬(stdio) MCP 서버. 원격 HTTP MCP 서버만 지원한다.
- 도구 실행 전에 사람이 승인하는 기능(human approval). 구조만 확장 가능하게 둔다.

## 핵심 설계: 모든 실행은 Run이다
채팅과 비동기 작업을 따로 만들지 않고, 하나의 **Run** 개념으로 합친다.

- **Run**은 "대화에 user 메시지 하나가 들어와서 agent가 최종 응답을 낼 때까지"의 실행 한 번이다. 이 사이에 도구 호출이 여러 번 일어날 수 있다.
- 모든 Run은 **worker 프로세스**가 실행한다. API 서버는 Run을 큐에 넣고 바로 반환한다.
- 진행 상황은 `run_events`에 기록한다. 클라이언트는 SSE로 구독한다.
  - 채팅 UI: Run을 만든 직후 SSE를 구독해서 토큰 단위로 보여준다.
  - 비동기 API: Run id만 받아두고 나중에 `GET /api/runs/{id}`로 결과를 조회한다.

이렇게 하면 HTTP 연결이 끊겨도 실행이 계속되고, 새로고침해도 진행 중인 응답을 이어서 볼 수 있다. 같은 실행 경로를 쓰므로 테스트도 한 곳에 모인다.

```
Browser ──POST /conversations/{id}/messages──▶ API ──INSERT runs(queued)──▶ Postgres
   ▲                                                                         │
   │ SSE /runs/{id}/events          LISTEN run_events ◀── NOTIFY ────────────┤
   └──────────────────────────────── API                                      │
                                                                              ▼
                                Worker ── SELECT … FOR UPDATE SKIP LOCKED ── runs
                                  │
                                  ├─▶ Anthropic Messages API (stream)
                                  └─▶ Sandbox container (docker exec: bash / 파일 편집)
```

### 큐: Postgres를 그대로 쓴다
Redis나 Celery를 추가하지 않는다.

- worker는 `SELECT … FROM runs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`로 Run을 하나 가져가서 `running`으로 바꾼다.
- 새 Run이 들어오면 `NOTIFY run_queued`를 보낸다. worker는 LISTEN하다가 깨어나고, 놓친 알림에 대비해 5초마다 polling도 한다.
- worker마다 동시 실행 수 상한을 둔다(`AGENT_MANAGER_WORKER_CONCURRENCY`, 기본 4).
- worker가 죽었을 때를 대비해 `heartbeat_at`을 둔다. `running` 상태인데 heartbeat가 60초 넘게 끊긴 Run은 다른 worker가 `failed`(error: worker lost)로 처리한다.
  - 자동 재시도는 하지 않는다. 도구가 이미 부수효과를 냈을 수 있어서다.

### 이벤트 스트리밍
- worker는 `run_events(run_id, seq, type, data)`를 INSERT하고 `NOTIFY run_events, '<run_id>:<seq>'`를 보낸다.
- 텍스트 delta는 100ms 단위로 모아서 저장한다. 토큰마다 저장하면 row가 너무 많아진다.
- SSE 엔드포인트의 동작:
  1. `Last-Event-ID`(또는 `?after=seq`) 이후의 이벤트를 DB에서 먼저 보낸다.
  2. 그 다음 LISTEN으로 실시간 이벤트를 보낸다.
  3. Run이 끝나면 `done` 이벤트를 보내고 연결을 닫는다.
- 브라우저 `EventSource`는 `Authorization` 헤더를 붙일 수 없다. 그래서 frontend는 `fetch` + `ReadableStream`으로 SSE를 직접 파싱한다.

이벤트 타입:

| type | data |
|---|---|
| `run_started` | `{model}` |
| `thinking_delta` | `{text}`: 요약된 사고 과정(`display: "summarized"`) |
| `text_delta` | `{text}` |
| `tool_call` | `{id, name, input}` |
| `tool_result` | `{id, output, isError}`: 출력은 최대 30KB로 자른다 |
| `message` | `{messageId}`: assistant/tool 메시지 하나가 DB에 확정됐다 |
| `usage` | `{inputTokens, outputTokens, cacheReadInputTokens}` |
| `run_finished` | `{status, error?}` |

## Agent loop (worker)
`services/runtime/loop.py`에 직접 작성한 loop를 둔다.

SDK의 Tool Runner를 쓰지 않는 이유는 다음 세 가지다.
- 토큰 단위로 스트리밍해야 한다.
- 턴마다 DB에 저장하고 취소 여부를 확인해야 한다.
- 샌드박스 도구 실행을 직접 제어해야 한다.

```
history = DB의 conversation 메시지 (content block 원본 JSON 그대로)
for turn in range(agent.max_turns):          # 기본 30
    check_cancel()
    async with client.beta.messages.stream(
        model=agent.model, max_tokens=64000,
        system=agent.system_prompt,
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": agent.effort},
        tools=build_tools(agent), mcp_servers=build_mcp(agent),
        betas=[...], fallbacks="default",
        messages=history,
    ) as stream: ...  → delta를 run_events로
    response = await stream.get_final_message()
    append assistant message (response.content 전체)   # thinking block 포함, 수정 금지
    match stop_reason:
        end_turn / refusal       → 종료
        pause_turn               → 그대로 다시 요청 (서버 도구 반복 한도)
        max_tokens + tool_use    → 실패 처리 (잘린 입력은 실행하지 않음)
        tool_use                 → 샌드박스에서 실행 → tool_result를 user 메시지 하나로 append
max_turns 초과 → failed("turn limit exceeded")
```

### 지켜야 할 규칙
- **대화 기록은 append-only다.** assistant `content`를 블록 단위 원본 JSON(JSONB)으로 저장하고, 다음 요청에 그대로 다시 보낸다.
  - Opus 5.5는 thinking block이 대화에 묶여 있어서, 기록을 수정하면 thinking이 무효가 된다.
  - 그래서 "메시지 수정"이나 "재생성" 기능은 새 대화로 분기하는 방식으로만 만든다.
- **thinking**은 `adaptive`로 둔다. Opus 5.5에서는 끌 수 없다. 사용자가 볼 수 있게 `display: "summarized"`로 요청한다.
- **effort**는 agent 설정이다. 기본값은 `medium`(Opus 5.5 기본값)이고 `low`부터 `max`까지 고를 수 있다.
- **거절 대비 fallback**: `server-side-fallback-2026-07-01` beta와 `fallbacks: "default"`를 켠다. `stop_reason == "refusal"`이면 `stop_details`를 Run 에러로 기록한다.
- **forced tool_choice는 쓰지 않는다.** Opus 5.5에서 400이 난다. 항상 `auto`로 둔다.
- **prompt caching**: system prompt와 도구 목록은 고정이므로 top-level `cache_control`로 캐시한다. `usage.cache_read_input_tokens`를 Run에 기록해서 캐시가 잘 맞는지 확인한다.
- **에러 처리**
  - `RateLimitError`나 5xx: SDK 기본 재시도(2회) 뒤에도 실패하면 Run을 `failed`로 둔다.
  - 400: 즉시 `failed`로 두고 메시지를 기록한다.

## 도구
agent마다 켤 도구를 고른다(`tools` JSONB).

| 도구 | 종류 | 실행 위치 |
|---|---|---|
| `bash` | Anthropic 정의 client tool `bash_20250124` | 샌드박스 컨테이너 (`docker exec`) |
| `text_editor` | Anthropic 정의 client tool `text_editor_20250728` | 샌드박스 컨테이너. 경로는 `/workspace` 밖으로 못 나간다 |
| `web_search` | 서버 도구 `web_search_20260209` | Anthropic |
| `web_fetch` | 서버 도구 `web_fetch_20260209` | Anthropic |
| MCP | MCP connector (`mcp_servers` + `mcp_toolset`, beta `mcp-client-2025-11-20`) | 원격 MCP 서버 (Anthropic이 직접 연결) |

### 샌드박스
`services/runtime/sandbox.py`에 `Sandbox` 인터페이스를 두고, 구현체는 `DockerSandbox`와 테스트용 `FakeSandbox` 두 가지를 만든다.

- **단위**: 대화 하나에 컨테이너 하나를 둔다. 같은 대화 안에서는 파일과 설치한 패키지가 유지된다.
  - 대화마다 named volume(`agent-ws-<conversation_id>`)을 만들어 `/workspace`에 마운트한다.
- **이미지**: `docker/sandbox/Dockerfile`에 python, node, git, curl, ripgrep을 넣는다. 비 root 사용자 `agent`(uid 1000)로 실행한다.
- **격리 설정**
  - 네트워크: 기본은 `network_mode=none`이다. agent 설정 `sandbox_network=true`일 때만 bridge로 연결한다.
  - 리소스: `mem_limit=1g`, `nano_cpus=1e9`, `pids_limit=256`
  - 권한: `cap_drop=ALL`, `security_opt=no-new-privileges`, 루트 파일시스템은 read-only이고 `/tmp`는 tmpfs로 둔다.
- **명령 실행**: 명령 하나의 timeout은 120초다. stdout/stderr는 30KB에서 자르고 잘렸다는 사실을 표시한다.
- **수명**
  - 첫 도구 호출 때 컨테이너를 만든다.
  - 30분 동안 쓰지 않으면 worker의 reaper가 stop한다. 다음 호출 때 다시 start한다.
  - 대화를 삭제하면 컨테이너와 volume도 지운다.
- **⚠️ 보안 주의**: worker가 `/var/run/docker.sock`을 마운트하면 사실상 호스트 root 권한을 갖는다.
  - 개발 환경에서는 이대로 쓴다.
  - 운영에서는 다음 중 하나로 바꿔야 한다.
    - gVisor(`runtime=runsc`)
    - rootless Docker / Sysbox
    - 별도 sandbox 호스트로 분리
  - `DockerSandbox`가 `runtime` 옵션을 받도록 만들어 둔다.

### MCP 서버 등록
- admin이 MCP 서버를 등록한다: `mcp_servers` 테이블에 name, url, authorization token을 넣는다.
- agent는 그중 몇 개를 고른다(`agent_mcp_servers`).
- token은 DB에 암호화해서 저장한다.
  - 키는 환경변수 `AGENT_MANAGER_SECRET_KEY`로 받고, `cryptography`의 Fernet을 쓴다.
  - API 응답에는 token을 절대 내보내지 않는다(`hasToken: bool`만).

## 데이터 모델 (Alembic 0002)
- `agents`에 추가할 컬럼
  - `model` varchar, 기본값 `claude-opus-5-5`
  - `effort` varchar, 기본값 `medium`. CHECK로 `low|medium|high|xhigh|max`만 허용한다.
  - `max_turns` int, 기본값 30
  - `tools` JSONB, 기본값 `{}`. 예: `{"bash": true, "textEditor": true, "webSearch": false, "webFetch": false}`
  - `sandbox_network` bool, 기본값 false
- `mcp_servers`
  - 컬럼: id, name unique, url, token_encrypted nullable, created_at
- `agent_mcp_servers`
  - 컬럼: agent_id, mcp_server_id
  - PK는 두 컬럼이고, 둘 다 CASCADE
- `conversations`
  - 컬럼: id, agent_id, user_id, title, sandbox_container_id nullable, created_at, updated_at, deleted_at
  - agent_id는 FK agents ON DELETE CASCADE다. agent를 purge하면 대화도 지운다. soft delete일 때는 대화를 남겨두되 새 Run은 막는다.
- `messages`
  - 컬럼: id, conversation_id, seq, role(`user|assistant`), content JSONB(블록 배열 원본), run_id nullable, created_at
  - UNIQUE (conversation_id, seq)
- `runs`
  - 컬럼: id, conversation_id, user_id, trigger(`chat|api`), status(`queued|running|succeeded|failed|cancelled`), cancel_requested bool, error, model, input_tokens, output_tokens, cache_read_input_tokens, heartbeat_at, created_at, started_at, finished_at
  - 인덱스: (status, created_at). 한 대화에서 동시에 활성 상태인 Run은 하나뿐이다. partial unique index로 보장한다.
- `run_events`
  - 컬럼: run_id, seq, type, data JSONB, created_at
  - PK는 (run_id, seq)

## 권한
- agent를 **실행**할 수 있는 조건은 그 agent가 **보이는 것**이다. 기존 `visible_agents_clause`를 그대로 쓴다.
  - Archestra의 `agent_users.level = use` 의미와 같다.
- 실행할 수 없는 경우
  - `agent_type = mcp_gateway`는 실행 대상이 아니다(400).
  - 삭제된 agent도 실행할 수 없다(404).
- **대화와 Run은 만든 사용자만** 보고 조작할 수 있다. 다른 사람이 접근하면 404로 응답해서 존재 여부를 드러내지 않는다.
- 대화 중간에 agent가 안 보이게 되면(scope 변경이나 팀 탈퇴) 새 메시지를 보낼 때 404가 난다.
- `runtime` 관련 설정(model, tools, MCP)의 수정 권한은 기존 `can_modify`를 따른다.
- MCP 서버 등록과 삭제는 admin만 할 수 있다.

## API
| Method | Path | 설명 |
|---|---|---|
| GET/POST | `/api/mcp-servers` | 목록 / 등록 (admin) |
| PUT/DELETE | `/api/mcp-servers/{id}` | admin |
| GET | `/api/conversations` | 내 대화 목록 (`agentId` 필터, 최신순, 페이지네이션) |
| POST | `/api/conversations` | `{agentId, title?}` |
| GET | `/api/conversations/{id}` | 대화와 메시지 전체 |
| PATCH/DELETE | `/api/conversations/{id}` | 제목 변경 / 삭제 (샌드박스 정리 포함) |
| POST | `/api/conversations/{id}/messages` | `{content}` → user 메시지를 저장하고 Run을 만든다. 응답은 `{message, run}`. 이미 활성 Run이 있으면 409 |
| POST | `/api/agents/{id}/runs` | **비동기 실행**: `{input}` → 대화를 새로 만들고 Run을 큐에 넣는다(trigger=api). 응답은 202 + `{run}` |
| GET | `/api/runs` | 내 Run 목록 (`status`, `agentId`, `trigger` 필터) |
| GET | `/api/runs/{id}` | 상태, usage, error, 마지막 assistant 텍스트(`output`) |
| GET | `/api/runs/{id}/events` | SSE (`text/event-stream`, `Last-Event-ID`로 이어받기) |
| POST | `/api/runs/{id}/cancel` | 취소를 요청한다. worker가 턴 사이와 도구 실행 중에 확인하고 `cancelled`로 바꾼다 |

## Frontend
- **`/chat`**: 왼쪽에 대화 목록, 오른쪽에 대화 화면을 둔다. 새 대화를 만들 때 고르는 agent의 기본값은 사용자의 default agent다.
- **`/chat/[conversationId]`** 화면 구성
  - 메시지 렌더링
    - text: markdown
    - thinking: 접힌 블록
    - tool_call / tool_result: 접을 수 있는 카드에 bash 명령, 출력, 파일 diff를 보여준다
  - 입력창은 Enter로 보내고 Shift+Enter로 줄을 바꾼다. 실행 중에는 Stop 버튼을 보여준다.
  - 새로고침했을 때 활성 Run이 있으면 SSE에 다시 붙는다.
- **`/runs`**: Run 이력 테이블(상태, agent, trigger, 토큰, 소요 시간). 행을 누르면 해당 대화로 간다.
- **agent 폼에 "Runtime" 섹션 추가**: model, effort, max turns, 도구 토글, 샌드박스 네트워크, MCP 서버 선택
- **agent 목록**: 각 행에 "Chat" 버튼을 추가한다.
- **`/settings/mcp-servers`**: MCP 서버 관리 (admin)
- 새 의존성: `react-markdown` + `remark-gfm`

## Backend 디렉토리 추가분
```
backend/app/
├── worker.py                     # python -m app.worker: 큐 소비, reaper, heartbeat
├── models/runtime.py             # Conversation, Message, Run, RunEvent, McpServer, AgentMcpServer
├── schemas/runtime.py
├── repositories/{conversation,run,run_event,mcp_server}.py
├── services/
│   ├── conversation.py           # 생성/메시지 추가/Run 생성 + 권한 검사
│   └── runtime/
│       ├── llm.py                # LLM 인터페이스 + AnthropicLLM (테스트에서 FakeLLM으로 교체)
│       ├── loop.py               # agent loop
│       ├── tools.py              # 도구 정의 빌드, tool_use → sandbox 실행 디스패치
│       ├── sandbox.py            # Sandbox / DockerSandbox / FakeSandbox
│       ├── events.py             # run_events 기록 + NOTIFY, delta 버퍼링
│       └── crypto.py             # Fernet
├── api/{conversations,runs,mcp_servers}.py
docker/sandbox/Dockerfile
```
- 의존성 추가: `anthropic`, `docker`, `cryptography`, `sse-starlette`
- docker-compose에 추가할 것
  - `worker` 서비스: 같은 backend 이미지를 쓰고 `command: python -m app.worker`로 실행한다. docker.sock을 마운트한다.
  - `sandbox` 이미지 빌드 타깃
- Makefile에 추가할 것: `make worker`, `make sandbox-image`

## 구현 순서
각 단계가 끝날 때마다 테스트, lint, build를 통과시키고 커밋한다.

1. **Runtime 설정**
   - agents 컬럼 추가(migration 0002)
   - 스키마/폼 "Runtime" 섹션, `make gen-api`
2. **실행 기반 (도구 없이 채팅)**
   - conversations, messages, runs, run_events 테이블
   - worker와 큐, 이벤트와 SSE
   - `AnthropicLLM`과 loop
   - `/chat` UI
3. **샌드박스와 내장 도구**
   - sandbox 이미지와 `DockerSandbox`
   - bash, text_editor
   - reaper
   - UI에 tool 카드 추가
4. **서버 도구와 MCP**
   - web_search, web_fetch
   - `mcp_servers` 등록/암호화, MCP connector
   - 설정 페이지
5. **비동기 실행과 이력**
   - `POST /api/agents/{id}/runs`, `/api/runs`, 취소
   - `/runs` 페이지
6. **문서**: README, `data-model.md`, `sequence-diagrams.md` 갱신

## 테스트
- `FakeLLM`: 미리 정한 응답 스크립트(text, tool_use, pause_turn, refusal, max_tokens)를 스트리밍으로 흉내 낸다. 실제 API는 호출하지 않는다.
- `FakeSandbox`: 명령과 결과를 기록한다.
- 핵심 케이스
  - 보이지 않는 agent로 대화를 만들면 404가 난다. `mcp_gateway` agent는 400이다.
  - 다른 사용자의 대화나 Run에 접근하면 404가 난다.
  - 활성 Run이 있는 대화에 메시지를 보내면 409가 난다.
  - tool_use → tool_result → end_turn 순서로 진행했을 때 messages가 올바른 순서로 append된다. assistant content 원본이 보존된다.
  - pause_turn이 오면 다시 요청한다. max_turns를 넘으면 failed가 된다. max_tokens로 tool_use가 잘리면 실행하지 않고 failed가 된다.
  - 취소를 요청하면 다음 턴 전에 cancelled가 된다.
  - heartbeat가 끊긴 running Run을 reaper가 failed로 바꾼다.
  - SSE: `Last-Event-ID` 이후 이벤트만 다시 보내고, 끝나면 `done`을 보낸다.
  - MCP token이 API 응답에 나오지 않는다.
- `DockerSandbox` 통합 테스트는 Docker가 있을 때만 돈다(`@pytest.mark.docker`).
  - 네트워크 차단, `/workspace` 밖 경로 거부, timeout을 확인한다.
- 실제 Anthropic API를 쓰는 E2E는 자동 테스트에 넣지 않는다. 수동으로 확인한다.

## 구현 중 변경사항
- **SSE 라이브러리 없이 구현**: `sse-starlette` 대신 FastAPI `StreamingResponse`로 직접 만들었다.
  - LISTEN 연결은 프로세스마다 하나(`app/pubsub.py`의 `Notifier`)를 두고 구독자에게 나눠 준다.
  - 알림은 깨우기 용도일 뿐이다. 데이터는 DB에서 다시 읽고, 2초마다 polling도 한다.
- **`conversations.sandbox_container_id` 제거**: 컨테이너 이름이 `agent-sandbox-<conversation id>`로 정해지므로 저장할 필요가 없다.
- **대화 삭제 시 샌드박스 정리**: API 서버는 Docker 소켓에 접근하지 않는다. 대신 worker의 reaper가 대화가 없어진 컨테이너와 volume을 지운다(30초 주기).
- **bash 세션**: 명령마다 새 `bash -c`로 실행한다.
  - 작업 디렉토리는 컨테이너의 `/tmp/.agent_cwd`에 저장해서 다음 호출에서 이어 쓴다.
  - 환경변수와 백그라운드 프로세스는 유지되지 않는다.
  - `restart`는 작업 디렉토리를 `/workspace`로 되돌린다.
- **명령어 허용 목록(allowlist)을 두지 않음**: 범용 agent에 allowlist는 현실적이지 않다. 대신 격리로 막는다.
  - 비 root 사용자, 모든 capability 제거, `no-new-privileges`
  - 읽기 전용 루트 파일시스템, 네트워크 차단(기본값)
  - 메모리·CPU·프로세스 수 제한, 명령 timeout
- **파일 편집 도구**: `text_editor_20250728`에는 `undo_edit`가 없어서 지원하지 않는다. `create`는 기존 파일을 백업 없이 덮어쓴다.
- **모델 선택**: `claude-opus-5-5`(기본), `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` 중에서 고른다.
  - `fallbacks: "default"`는 Haiku 5.5를 제외하고 보낸다. Haiku 5.5는 서버 측 fallback을 지원하지 않는다.
- **API 키 읽기**: `ANTHROPIC_API_KEY`를 설정(`.env`)에서 읽어 SDK client에 넘긴다. pydantic-settings는 `.env`를 `os.environ`에 넣지 않기 때문이다. 값이 없으면 SDK가 자체적으로 자격 증명을 찾는다.
- **MCP 서버 URL**: `https://`만 허용한다. Claude가 Anthropic 서버에서 직접 연결하므로 공개 HTTPS 주소여야 한다.
- **MCP 서버 목록 권한**: 모든 사용자가 볼 수 있다(agent 폼에서 고르기 위해). token은 응답에 넣지 않는다.

## 검증
- `make test`: 74개 테스트
  - 실행 경로는 `FakeLLM`과 `FakeSandbox`로 검증한다.
  - `test_llm.py`는 가짜 HTTP 응답으로 실제 SDK 요청 형식과 스트림 파싱을 확인한다.
  - `test_sandbox_docker.py`는 Docker와 sandbox 이미지가 있을 때만 돈다. 실제 컨테이너에서 격리, 영속성, timeout, 정리를 확인한다.
- **실제 Anthropic API 호출은 자동 테스트에 넣지 않았다.** `ANTHROPIC_API_KEY`를 설정하고 `make dev-worker`로 수동 확인한다.
