# 컴포넌트별 시퀀스 다이어그램

주요 기능이 프론트엔드에서 DB까지 어떤 순서로 흐르는지 정리한 문서입니다. 데이터 구조는 [data-model.md](data-model.md)를 참고하세요.

## 참여 컴포넌트

```mermaid
flowchart LR
    subgraph Frontend["Frontend (Next.js)"]
        Page["Page component<br/>components/**"]
        Hook["Query hook<br/>lib/queries/*"]
        Client["API client<br/>lib/api/client.ts"]
        Auth["Token store<br/>lib/auth.ts"]
    end
    subgraph Backend["Backend (FastAPI)"]
        Router["Router<br/>app/api/*"]
        Deps["get_actor<br/>app/api/deps.py"]
        Service["Service<br/>app/services/*"]
        Access["Access rules<br/>services/access.py"]
        Repo["Repository<br/>app/repositories/*"]
    end
    DB[("PostgreSQL")]

    Page --> Hook --> Client
    Client <--> Auth
    Client -- "HTTP + Bearer JWT" --> Router
    Router --> Deps
    Router --> Service
    Service --> Access
    Service --> Repo --> DB
```

| 계층 | 책임 |
|---|---|
| Page component | 화면, 사용자 입력, URL 상태 |
| Query hook | 캐시 키, 요청, 성공 시 캐시 무효화 |
| API client | 타입이 붙은 HTTP 호출, 토큰 첨부, 401 처리, 에러를 `ApiError`로 변환 |
| Router | 요청 파싱·검증, 서비스 호출 |
| get_actor | JWT 검증 → `Actor` (사용자 + 팀 역할) 생성 |
| Service | 비즈니스 규칙, 트랜잭션 commit, 응답 조립(`hydrate`) |
| Access rules | 볼 수 있는/수정 가능한 agent 판정 (SQL 조건 + Python 함수) |
| Repository | DB 접근만 담당 (규칙 없음) |

## 목차

1. [인증된 요청의 공통 처리](#1-인증된-요청의-공통-처리)
2. [로그인](#2-로그인)
3. [인증 가드와 세션 만료](#3-인증-가드와-세션-만료)
4. [Agent 목록 조회](#4-agent-목록-조회)
5. [Agent 생성](#5-agent-생성)
6. [Agent 수정](#6-agent-수정)
7. [Agent 삭제 · 복원 · 영구 삭제](#7-agent-삭제--복원--영구-삭제)
8. [라벨 동기화](#8-라벨-동기화)
9. [기본 Agent 지정](#9-기본-agent-지정)
10. [팀 멤버 관리 (admin)](#10-팀-멤버-관리-admin)
11. [Agent 실행: 채팅 메시지 → Run → SSE](#11-agent-실행-채팅-메시지--run--sse)
12. [도구 호출과 샌드박스](#12-도구-호출과-샌드박스)
13. [취소와 worker 장애](#13-취소와-worker-장애)
14. [비동기 실행 API](#14-비동기-실행-api)

---

## 1. 인증된 요청의 공통 처리

`/api/auth/login`을 제외한 모든 API는 라우터 실행 전에 `get_actor` 의존성을 거칩니다. 이후 다이어그램에서는 이 과정을 "get_actor"로 줄여 표시합니다.

```mermaid
sequenceDiagram
    autonumber
    participant C as API client
    participant R as Router
    participant D as get_actor (deps.py)
    participant S as security.py
    participant U as user repository
    participant DB as PostgreSQL

    C->>R: 요청 + Authorization: Bearer JWT
    R->>D: 의존성 실행
    alt Authorization 헤더 없음
        D-->>C: 401 Not authenticated
    end
    D->>S: decode_access_token(token)
    S-->>D: user_id 또는 None (서명 오류/만료)
    D->>U: get_by_id(user_id)
    U->>DB: SELECT users
    alt 토큰 무효 또는 사용자 없음
        D-->>C: 401 Invalid or expired token
    end
    D->>U: get_team_memberships(user_id)
    U->>DB: SELECT teams JOIN team_members
    D-->>R: Actor(user, team_roles)
    Note over R: admin 전용 라우트는 require_admin이<br/>추가로 검사 (아니면 403)
```

---

## 2. 로그인

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant LP as LoginPage
    participant H as useLogin
    participant T as Token store
    participant API as POST /api/auth/login
    participant U as user repository
    participant DB as PostgreSQL

    User->>LP: 이메일·비밀번호 입력 후 Sign in
    LP->>H: mutate({email, password})
    H->>API: POST (토큰 없음)
    API->>U: get_by_email(소문자 변환)
    U->>DB: SELECT users
    alt 사용자 없음 또는 bcrypt 불일치
        API-->>H: 401 Invalid email or password
        H-->>LP: error.message 표시
    else 성공
        API->>API: create_access_token(user.id)
        API->>U: get_team_memberships(user.id)
        API-->>H: {accessToken, tokenType, user(MeRead)}
        H->>T: setToken(accessToken)
        H->>H: queryClient.clear() 후 ["me"]에 user 저장
        H-->>LP: onSuccess
        LP->>LP: router.replace("/agents")
    end
```

---

## 3. 인증 가드와 세션 만료

보호된 페이지는 모두 `AppShell`로 감싸져 있습니다. 토큰 저장소를 구독하므로, 다른 요청이 401을 받아 토큰이 지워지면 즉시 로그인 화면으로 이동합니다.

```mermaid
sequenceDiagram
    autonumber
    participant AS as AppShell
    participant T as Token store
    participant M as useMe
    participant C as API client
    participant API as Backend

    AS->>T: subscribeToken() + getToken()
    alt 토큰 없음
        AS->>AS: router.replace("/login")
    else 토큰 있음
        AS->>M: ["me"] 조회
        M->>C: GET /api/auth/me
        C->>API: Bearer 토큰 첨부
        API-->>C: 200 MeRead
        M-->>AS: me 데이터
        AS->>AS: 헤더/내비게이션 렌더링, children(me) 호출
    end

    Note over AS,API: 이후 아무 요청에서나 세션이 만료되면
    C->>API: 임의의 API 요청
    API-->>C: 401
    C->>T: clearToken()
    T-->>AS: 구독 알림 (hasToken = false)
    AS->>AS: router.replace("/login")
```

---

## 4. Agent 목록 조회

`GET /api/agents`. 필터 조건은 URL에 있고, 라벨 필터는 `env:prod|dev` 형식에 키 사이를 세미콜론으로 이어 붙입니다 (예: `env:prod|dev` 와 `owner:a` 를 함께 걸면 키끼리 AND, 값끼리 OR).

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant P as AgentsListPage
    participant Q as useAgentsPaginated
    participant R as agents router
    participant S as agent service
    participant A as access rules
    participant AR as agent repository
    participant RR as team/user/label repositories
    participant DB as PostgreSQL

    User->>P: 검색어 입력 · 필터 · 정렬 · 페이지 이동
    P->>P: useUrlState가 URL 쿼리 갱신 (검색어는 300ms debounce)
    P->>Q: params(limit, offset, sortBy, status, name, scope, teamIds, labels)
    Q->>R: GET /api/agents?...
    R->>R: get_actor
    R->>R: teamIds, labels 파싱 (형식 오류면 400)
    R->>S: list_agents(actor, AgentListFilters)
    alt status=deleted
        S->>A: modifiable_agents_clause(actor)
    else status=active
        S->>A: visible_agents_clause(actor)
    end
    A-->>S: SQL WHERE 조건
    S->>AR: list_paginated(filters, visibility)
    AR->>DB: SELECT count(*) WHERE 권한 AND 필터
    AR->>DB: SELECT agents WHERE ... ORDER BY ... LIMIT/OFFSET
    AR-->>S: agents, total
    S->>RR: hydrate - 배치 쿼리 4번
    RR->>DB: agent_teams JOIN teams
    RR->>DB: agent_users JOIN users
    RR->>DB: agent_labels JOIN label_keys, label_values
    RR->>DB: users (작성자 이름)
    S->>A: agent마다 can_modify() 계산
    S-->>R: Paginated[AgentRead]
    R-->>Q: 200 {data, pagination}
    Q-->>P: 테이블 렌더링 (이전 페이지 데이터를 유지하며 교체)
```

---

## 5. Agent 생성

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant F as AgentForm
    participant Q as useCreateAgent
    participant R as agents router
    participant S as agent service
    participant TR as team repository
    participant UR as user repository
    participant AR as agent repository
    participant JR as agent_team / agent_user repositories
    participant LR as label repository
    participant DB as PostgreSQL

    User->>F: 폼 입력 후 Create agent
    F->>F: zod 검증 (이름, team scope면 팀 1개 이상, 라벨 키 중복)
    F->>Q: mutate(AgentCreate)
    Q->>R: POST /api/agents
    R->>R: get_actor + Pydantic 검증
    R->>S: create_agent(actor, body)
    alt scope=org 이고 admin 아님
        S-->>R: 403
    end
    opt scope=team
        S->>TR: existing_ids(teams)
        Note over S: 팀 없음/미존재 → 400<br/>비admin이 관리하지 않는 팀 → 403
    end
    opt scope=personal
        S->>UR: get_many(공유 대상) - 없는 사용자면 400
    end
    S->>AR: create(name, ..., author_id=actor.id)
    AR->>DB: INSERT agents
    S->>JR: agent_teams sync (team scope일 때만 행 생성)
    S->>JR: agent_users sync (personal일 때만 행 생성)
    S->>LR: sync_agent_labels (8번 참고)
    S->>DB: COMMIT
    S->>S: hydrate([agent])
    S-->>R: AgentRead
    R-->>Q: 201 AgentRead
    Q->>Q: ["agents"], ["members","default-agent"] 무효화
    Q-->>F: onSuccess
    F->>F: toast 후 /agents/{id}로 이동
```

---

## 6. Agent 수정

`PUT /api/agents/{id}`는 부분 수정입니다. 보낸 필드만 바뀌고, 보내지 않은 필드는 그대로입니다.

```mermaid
sequenceDiagram
    autonumber
    participant F as AgentForm (상세 페이지)
    participant Q as useUpdateAgent
    participant R as agents router
    participant S as agent service
    participant A as access rules
    participant AR as agent repository
    participant JR as agent_team / agent_user repositories
    participant LR as label repository
    participant DB as PostgreSQL

    F->>Q: mutate(AgentUpdate)
    Q->>R: PUT /api/agents/{id}
    R->>R: get_actor
    R->>S: update_agent(actor, id, body)
    S->>A: 활성 AND visible AND modifiable 조건
    S->>AR: get(id, where=조건)
    alt 없음 또는 수정 권한 없음
        S-->>R: 404 (존재 여부를 숨김)
    end
    S->>S: exclude_unset으로 보낸 필드만 추출
    Note over S: name/scope 등에 null → 400<br/>team·org → personal → 400<br/>비admin이 org로 변경 → 403
    S->>JR: 현재 팀 조회
    alt 새 scope = team
        S->>S: 팀 검증 - 비admin은 관리하는 팀만 추가/제거 가능 (아니면 403)
        S->>JR: agent_teams sync
    else 다른 scope로 변경
        S->>JR: agent_teams 비우기
    end
    alt 새 scope ≠ personal
        S->>JR: agent_users 비우기
    else users를 보냄
        S->>JR: agent_users sync
    end
    opt labels를 보냄
        S->>LR: sync_agent_labels
    end
    S->>AR: update_fields(변경된 컬럼, updated_at)
    S->>DB: COMMIT
    S-->>R: AgentRead (hydrate)
    R-->>Q: 200
    Q->>Q: ["agents"] 무효화
    Q-->>F: 새 updatedAt을 key로 폼을 다시 마운트
```

---

## 7. Agent 삭제 · 복원 · 영구 삭제

세 동작 모두 "수정 가능한 agent"에만 허용됩니다. 확인 대화상자는 `DeleteAgentDialog`를 함께 씁니다.

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant P as AgentsListPage
    participant R as agents router
    participant S as agent service
    participant AR as agent repository
    participant LR as label repository
    participant DB as PostgreSQL

    rect rgba(128,128,128,0.08)
    Note over User,DB: 삭제 (soft delete) - Active 탭
    User->>P: ⋯ 메뉴 → Delete → 확인
    P->>R: DELETE /api/agents/{id}
    R->>S: delete_agent
    S->>AR: get(활성 AND visible AND modifiable) - 없으면 404
    S->>AR: soft_delete
    AR->>DB: UPDATE agents SET deleted_at = now()
    AR->>DB: UPDATE member_settings SET default_agent_id = NULL
    S->>DB: COMMIT
    R-->>P: 200 {success}
    end

    rect rgba(128,128,128,0.08)
    Note over User,DB: 복원 - Deleted 탭
    User->>P: ⋯ 메뉴 → Restore
    P->>R: POST /api/agents/{id}/restore
    R->>S: restore_agent
    S->>AR: get(삭제됨 AND modifiable) - 없으면 404
    S->>AR: active_name_exists(name)
    alt 같은 이름의 활성 agent 존재
        S-->>P: 409 이름을 먼저 바꾸라는 메시지
    else
        AR->>DB: UPDATE agents SET deleted_at = NULL
        S->>DB: COMMIT
        R-->>P: 200 AgentRead
    end
    end

    rect rgba(128,128,128,0.08)
    Note over User,DB: 영구 삭제 - Deleted 탭
    User->>P: ⋯ 메뉴 → Delete permanently → 확인
    P->>R: DELETE /api/agents/{id}/permanent
    R->>S: purge_agent
    S->>AR: get(modifiable) - 없으면 404
    alt 아직 활성 상태
        S-->>P: 400 먼저 삭제해야 함
    else
        AR->>DB: DELETE agents (연결 테이블 CASCADE)
        S->>LR: prune_orphans
        S->>DB: COMMIT
        R-->>P: 200 {success}
    end
    end

    P->>P: 성공 시 ["agents"]와 기본 agent 캐시 무효화, toast
```

---

## 8. 라벨 동기화

`label_repository.sync_agent_labels`. agent 생성과 수정(labels를 보냈을 때)에서 같은 트랜잭션 안에서 호출됩니다.

```mermaid
sequenceDiagram
    autonumber
    participant S as agent service
    participant LR as label repository
    participant DB as PostgreSQL

    S->>LR: sync_agent_labels(agent_id, [(key, value), ...])
    LR->>DB: DELETE agent_labels WHERE agent_id
    loop 라벨마다
        LR->>DB: INSERT label_keys(key) ON CONFLICT DO NOTHING
        LR->>DB: SELECT label_keys.id
        LR->>DB: INSERT label_values(value) ON CONFLICT DO NOTHING
        LR->>DB: SELECT label_values.id
    end
    LR->>DB: INSERT agent_labels (agent_id, key_id, value_id)
    LR->>DB: DELETE label_keys - 어떤 agent도 쓰지 않는 키
    LR->>DB: DELETE label_values - 어떤 agent도 쓰지 않는 값
    LR-->>S: 완료 (commit은 서비스가 함)
```

`ON CONFLICT DO NOTHING`을 쓰기 때문에 같은 키를 동시에 만들어도 unique 제약 위반이 나지 않습니다.

---

## 9. 기본 Agent 지정

```mermaid
sequenceDiagram
    autonumber
    actor User as 사용자
    participant T as AgentsTable
    participant Q as useSetDefaultAgentId
    participant R as members router
    participant S as agent service
    participant UR as user repository
    participant DB as PostgreSQL

    User->>T: ⋯ 메뉴 → Set as my default (또는 Unset)
    T->>Q: mutate(agentId 또는 null)
    Q->>R: PUT /api/members/default-agent
    R->>R: get_actor
    opt agentId가 null이 아님
        R->>S: get_visible_active_agent(actor, agentId)
        S->>DB: SELECT agents WHERE 활성 AND visible
        Note over S: 볼 수 없거나 삭제된 agent → 404
    end
    R->>UR: set_default_agent_id(user, agentId)
    UR->>DB: member_settings INSERT 또는 UPDATE
    R->>DB: COMMIT
    R-->>Q: 200 {defaultAgentId}
    Q->>Q: ["members","default-agent"] 캐시를 응답으로 직접 갱신
    Q-->>T: Default 배지 이동
```

---

## 10. 팀 멤버 관리 (admin)

팀 멤버십은 접근제어의 입력이므로, 변경 후 사용자 정보와 agent 목록 캐시도 함께 무효화합니다.

```mermaid
sequenceDiagram
    autonumber
    actor Admin as 관리자
    participant P as TeamsSettingsPage
    participant Q as useUpsertTeamMember
    participant R as teams router
    participant TR as team repository
    participant UR as user repository
    participant DB as PostgreSQL

    Admin->>P: 멤버 추가 또는 역할 변경 (member ↔ team_admin)
    P->>Q: mutate({teamId, userId, role})
    Q->>R: PUT /api/teams/{teamId}/members/{userId}
    R->>R: get_actor + require_admin (아니면 403)
    R->>TR: get(teamId) - 없으면 404
    R->>UR: get_by_id(userId) - 없으면 404
    R->>TR: upsert_member
    TR->>DB: INSERT team_members ON CONFLICT (team_id, user_id) DO UPDATE role
    R->>DB: COMMIT
    R->>TR: get_members_for_teams([teamId])
    R-->>Q: 200 TeamRead (멤버 포함)
    Q->>Q: ["teams"], ["me"], ["agents"] 무효화
    Note over P: 이 사용자가 볼 수 있는 agent와<br/>수정 권한(canModify)이 다음 조회부터 바뀐다
```

---

## 11. Agent 실행: 채팅 메시지 → Run → SSE

API 서버는 Run을 큐(`runs` 테이블)에 넣고 바로 응답합니다. 실행은 별도의 worker 프로세스(`python -m app.worker`)가 맡고, 진행 상황은 `run_events`를 거쳐 SSE로 전달됩니다. 두 프로세스는 Postgres의 `LISTEN/NOTIFY`로 서로를 깨웁니다. 알림은 깨우기 용도일 뿐이고, 데이터는 항상 DB에서 다시 읽습니다. 그래서 알림을 놓쳐도 polling 주기만큼 늦어질 뿐입니다.

```mermaid
flowchart LR
    Browser["Browser<br/>ConversationView + useRunStream"]
    API["API (FastAPI)<br/>conversations, runs routers"]
    Worker["Worker<br/>app/worker.py + RunExecutor"]
    DB[("PostgreSQL<br/>runs, messages, run_events")]
    Claude["Claude API<br/>Messages (stream)"]
    Sandbox["Sandbox container<br/>per conversation"]

    Browser -- "POST messages / GET events (SSE)" --> API
    API -- "INSERT + NOTIFY run_queued" --> DB
    DB -- "NOTIFY run_events" --> API
    Worker -- "claim (SKIP LOCKED), INSERT events + NOTIFY" --> DB
    DB -- "NOTIFY run_queued" --> Worker
    Worker -- "stream" --> Claude
    Worker -- "docker exec" --> Sandbox
```

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant V as ConversationView
    participant S as useRunStream
    participant API as conversations / runs router
    participant DB as PostgreSQL
    participant W as Worker
    participant X as RunExecutor
    participant C as Claude API

    U->>V: 메시지 입력 후 Enter
    V->>API: POST /api/conversations/{id}/messages
    API->>API: 대화 소유자 확인, agent가 보이고 실행 가능한지 확인 (아니면 404/400)
    API->>DB: 활성 Run 확인 (있으면 409)
    API->>DB: INSERT messages(user), INSERT runs(queued), pg_notify('run_queued')
    API->>DB: COMMIT
    API-->>V: 201 {message, run}
    V->>V: 대화 다시 조회 → activeRun 생김
    V->>S: activeRun.id 구독 시작
    S->>API: GET /api/runs/{id}/events (fetch + ReadableStream)
    API->>DB: LISTEN run_events, 기존 이벤트 조회 (없음)

    DB-->>W: NOTIFY run_queued
    W->>DB: UPDATE runs SET status='running' WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)
    W->>X: execute()
    X->>DB: agent, 대화 기록, MCP 서버 조회
    X->>DB: run_events 'run_started' + NOTIFY
    loop 턴마다 (최대 agent.maxTurns)
        X->>C: messages.stream(system, history, tools, thinking adaptive, effort, fallbacks)
        C-->>X: thinking/text delta
        X->>DB: thinking_delta / text_delta (100ms 단위로 묶어서) + NOTIFY
        DB-->>API: NOTIFY run_events
        API-->>S: event: text_delta
        S-->>V: 진행 중인 출력 갱신
        C-->>X: 최종 메시지 (stop_reason, usage)
        X->>DB: usage 누적, INSERT messages(assistant, content 원본), 'message' 이벤트
        API-->>S: event: message
        S->>API: GET /api/conversations/{id} (저장된 메시지로 교체)
        alt stop_reason = tool_use
            Note over X: 12번 다이어그램 (도구 실행 후 다음 턴)
        else end_turn
            Note over X: 루프 종료
        end
    end
    X->>DB: UPDATE runs status='succeeded' + 'run_finished' 이벤트 (한 트랜잭션)
    API-->>S: event: run_finished, event: done
    S->>S: 대화·Run 캐시 무효화
```

stop_reason별 처리:

| stop_reason | 처리 |
|---|---|
| `end_turn` | assistant 메시지 저장 후 `succeeded` |
| `tool_use` | 저장 → 도구 실행 → tool_result를 user 메시지 **하나**로 저장 → 다음 턴 |
| `pause_turn` | 서버 도구(web search 등)가 반복 한도에 걸린 경우. 저장한 뒤 user 메시지 없이 같은 기록으로 다시 요청 |
| `max_tokens` + tool_use | 잘린 도구 입력은 실행하지 않는다. 저장하지 않고 `failed` |
| `refusal` | 부분 출력을 버리고(`turn_reset`) `failed`. `fallbacks: "default"`로 서버가 다른 모델로 재시도한 뒤에도 거절된 경우다 |

---

## 12. 도구 호출과 샌드박스

bash와 파일 편집 도구는 대화마다 하나씩 있는 컨테이너에서 실행합니다. 컨테이너는 처음 도구를 호출할 때 만들어집니다. web search/fetch와 MCP 도구는 Anthropic 서버가 직접 실행하므로 worker를 거치지 않고, 결과가 assistant content에 들어옵니다.

```mermaid
sequenceDiagram
    autonumber
    participant X as RunExecutor
    participant T as AgentToolbox
    participant P as DockerSandboxProvider
    participant D as Docker daemon
    participant B as agent-sandbox-{conversationId}
    participant DB as PostgreSQL

    X->>DB: 'tool_call' 이벤트 {id, name, input}
    X->>T: execute("bash", {command})
    T->>T: agent에서 켠 도구인지 확인 (아니면 is_error)
    alt 이번 Run에서 첫 도구 호출
        T->>P: get(conversationId, network=agent.sandboxNetwork)
        P->>D: 컨테이너 조회
        alt 없음 또는 네트워크 설정이 바뀜
            P->>D: run(image, user 1000, cap_drop ALL, read_only,<br/>network none, mem/cpu/pids 제한,<br/>volume agent-ws-{id} → /workspace)
        else 멈춰 있음 (idle reaper가 stop)
            P->>D: start
        end
    end
    T->>B: exec: timeout 120 bash -c wrapper "$command"
    Note over B: 이전 cd 위치에서 실행하고,<br/>끝난 위치를 /tmp/.agent_cwd에 저장
    B-->>T: exit code + stdout/stderr
    T->>T: 30KB 넘으면 가운데 생략, exit code·timeout 표시
    T-->>X: ToolOutput(content, is_error)
    X->>DB: 'tool_result' 이벤트
    X->>DB: INSERT messages(user, [tool_result …])
```

파일 편집 도구(`str_replace_based_edit_tool`)의 경로는 정규화한 뒤 `/workspace` 안인지 확인합니다. 읽기와 쓰기는 Docker archive API(`get_archive`/`put_archive`)로 합니다.

worker의 reaper는 30초마다 다음을 처리합니다.
- 30분 동안 쓰지 않은 컨테이너를 stop한다. volume은 남는다.
- 대화가 삭제된 컨테이너와 volume을 지운다.

---

## 13. 취소와 worker 장애

```mermaid
sequenceDiagram
    autonumber
    actor U as 사용자
    participant API as runs router
    participant DB as PostgreSQL
    participant X as RunExecutor
    participant H as watcher (같은 executor)
    participant R as reaper (다른 worker 포함)

    alt queued 상태에서 취소
        U->>API: POST /api/runs/{id}/cancel
        API->>DB: status='cancelled', cancel_requested=true, 'run_finished' 이벤트
    else running 상태에서 취소
        U->>API: POST /api/runs/{id}/cancel
        API->>DB: cancel_requested=true
        H->>DB: 2초마다 heartbeat_at 갱신 RETURNING cancel_requested
        H->>X: loop task cancel()
        X->>DB: finish_run(cancelled)
        Note over X,DB: 마지막 메시지가 tool_use면<br/>"Not executed" tool_result를 채워 넣는다
    end

    alt worker가 SIGTERM으로 종료
        X->>DB: finish_run(failed, "The worker stopped while running")
    else worker 프로세스가 죽음 (heartbeat 끊김)
        R->>DB: status='running' AND heartbeat_at < now() - 60s
        R->>DB: finish_run(failed, "stopped responding")
    end
```

자동으로 재시도하지는 않습니다. 도구가 이미 부수효과(파일 변경, 외부 호출)를 냈을 수 있기 때문입니다.

---

## 14. 비동기 실행 API

화면 없이 agent를 실행하고, 결과를 나중에 조회합니다. 내부적으로는 채팅과 같은 경로(대화 + Run)를 씁니다.

```mermaid
sequenceDiagram
    autonumber
    participant Cl as API 클라이언트
    participant API as runs router
    participant DB as PostgreSQL
    participant W as Worker

    Cl->>API: POST /api/agents/{agentId}/runs {input}
    API->>API: agent가 보이고 실행 가능한지 확인
    API->>DB: INSERT conversations(title=input 앞부분), messages(user), runs(trigger='api')
    API-->>Cl: 202 RunRead {id, status: queued}
    W->>DB: claim → 실행 (11번과 동일)
    loop 끝날 때까지
        Cl->>API: GET /api/runs/{id}
        API-->>Cl: RunDetail {status, output?, error?}
    end
    Note over Cl: polling 대신 GET /api/runs/{id}/events를 구독해도 된다.<br/>결과 대화는 /chat/{conversationId}에서 이어갈 수 있다
```
