# Agent Manager: Archestra의 Agent 관리 기능을 FastAPI + Next.js로 재구성

## Context
Archestra 플랫폼(Fastify + Drizzle + Next.js)의 Agent 관리 기능을 분석해서, 핵심 도메인을 **FastAPI + Next.js** 독립 프로젝트로 다시 구성한다.
- 위치: `~/git/agent-manager` (archestra 저장소 밖)
- 범위: Agent CRUD, 페이지네이션/검색/필터/정렬, 라벨, 팀 기반 접근제어(scope), 간단한 인증, soft delete/restore, 사용자별 기본 Agent
- 제외: Tool 할당, 정책, MCP Gateway/LLM Proxy, 버전 관리, built-in agent, 런타임, 이메일 트리거, import/export

## Archestra에서 가져올 설계 (참조 원본)
| 개념 | Archestra 원본 | 새 프로젝트 |
|---|---|---|
| agents 테이블 | `platform/backend/src/database/schemas/agent.ts:48` (soft delete, scope, agent_type) | `agents` 테이블 |
| 팀 매핑 | `schemas/agent-team.ts` (PK agent_id+team_id, CASCADE) | `agent_teams` |
| 사용자 공유 | `schemas/agent-user.ts` (level use/write) | `agent_users` |
| 라벨 | `schemas/agent-label.ts`, `label_keys`/`label_values` (키당 값 1개) | 같은 구조 |
| 조회 권한 | `models/agent.ts:2089` `findAccessibleIdsForUser` | `services/access.py` |
| 수정 권한 | `auth/agent-type-permissions.ts` `requireAgentModifyPermission` | `services/access.py` |
| 목록 API | `routes/agent.ts:101` (name, scope, teamIds, labels `k:v1\|v2;k2:v3`, status, sortBy) | `GET /api/agents` |
| 라벨 sync | `models/agent-label.ts:66` (전부 지우고 다시 넣은 뒤 고아 키/값 정리) | `repositories/label.py` |
| 프론트 목록/폼 | `frontend/src/app/agents/page.client.tsx`, `components/agent-form.tsx`, `lib/agent.query.ts` | `app/agents/*`, `lib/queries/agents.ts` |

### 가져올 비즈니스 규칙
- **scope** `personal | team | org`
  - 조회: admin은 전체를 본다. 그 외 사용자는 org 전체, 자신이 작성했거나 공유받은 personal, 자신이 속한 팀의 team agent를 본다.
  - 수정/삭제: admin은 항상 가능하다. org scope는 admin만 가능하다. team scope는 `team_admin` 역할이면서 해당 팀 멤버여야 한다. personal은 작성자만 가능하다.
- **생성/수정 검증**
  - admin이 아니면 `org` scope를 쓸 수 없다.
  - team scope는 팀이 1개 이상 필요하고, 사용자가 속한 팀만 지정할 수 있다. scope가 team이 아니면 teams를 비운다.
  - 공유된(team/org) agent를 personal로 되돌릴 수 없다(400).
- **삭제**는 soft delete(`deleted_at`)다.
  - `status=deleted` 목록은 delete 권한이 필요하다.
  - restore할 때 활성 agent 중 같은 이름이 있으면 409를 반환한다.
  - 영구 삭제(`/permanent`)는 별도 API로 둔다.
  - 삭제 시 이 agent를 가리키는 `members.default_agent_id`를 NULL로 만든다.
- **이름**: DB 유니크 제약은 없다. Archestra와 동일하다.
- **에러**: 형식은 `{ "error": { "message", "type" } }`로 통일한다(Archestra `ApiError` 형식).
- **수정 권한이 없을 때**: 403 대신 404를 반환한다(존재 여부 노출 방지).

## 기술 스택
- **Backend**
  - Python 3.12, FastAPI, Pydantic v2
  - SQLAlchemy 2.0 async + asyncpg, Alembic
  - 인증: JWT(`pyjwt`) + `bcrypt` (passlib은 유지보수 중단 + 최신 bcrypt와 비호환이라 직접 사용)
  - 패키지 관리: `uv`, lint: `ruff`
  - 테스트: pytest + httpx AsyncClient, testcontainers 대신 docker-compose의 테스트 DB
- **Frontend**
  - Next.js 15 App Router, TypeScript
  - TanStack Query v5, react-hook-form + zod
  - shadcn/ui + Tailwind
  - API 타입은 `openapi-typescript`로 FastAPI `/openapi.json`에서 생성한다(Archestra의 generated client 패턴).
- **Infra**: `docker-compose.yml`로 postgres:16, backend(:8000), frontend(:3000)를 띄우고 `Makefile`을 둔다.

## 디렉토리 구조
```
agent-manager/
├── docker-compose.yml, Makefile, README.md, .env.example
├── backend/
│   ├── pyproject.toml, alembic.ini, alembic/versions/0001_init.py
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, 예외 핸들러, 라우터 등록
│   │   ├── config.py            # pydantic-settings (AGENT_MANAGER_* env)
│   │   ├── db.py                # async engine/session, get_db dependency
│   │   ├── errors.py            # ApiError + 통일된 에러 응답 핸들러
│   │   ├── models/              # SQLAlchemy ORM: user, team, team_member, agent, agent_team, agent_user, label_key, label_value, agent_label
│   │   ├── schemas/             # Pydantic: agent(Create/Update/Read/ListQuery), team, auth, common(Paginated[T])
│   │   ├── repositories/        # DB 접근은 여기서만 (Archestra의 "Model-only DB access" 원칙)
│   │   │   ├── agent.py         # create, get, list_paginated(filter/sort), update, soft_delete, restore, purge
│   │   │   ├── agent_team.py    # sync, get_teams_for_agents (N+1 방지 batch)
│   │   │   ├── label.py         # get_or_create_key/value, sync_agent_labels, get_labels_for_agents, keys/values
│   │   │   └── team.py, user.py
│   │   ├── services/
│   │   │   ├── access.py        # accessible_agent_ids_clause(user), can_modify(user, agent)
│   │   │   └── agent.py         # 생성/수정 검증 규칙 (scope 상승, 팀 검증 등)
│   │   ├── api/
│   │   │   ├── deps.py          # current_user (Bearer JWT), require_admin
│   │   │   ├── auth.py          # POST /api/auth/login, GET /api/auth/me
│   │   │   ├── agents.py        # 아래 엔드포인트
│   │   │   ├── teams.py         # GET (전체), POST/PUT/DELETE + 멤버 관리 (admin)
│   │   │   └── members.py       # GET/PUT /api/members/default-agent
│   │   └── seed.py              # admin@example.com / member 사용자, 팀 2개, 샘플 agent
│   └── tests/
│       ├── conftest.py          # 테스트 DB, 트랜잭션 롤백, 사용자/팀 fixture
│       ├── test_agents_access.py
│       ├── test_agents_crud.py
│       └── test_labels.py
└── frontend/
    ├── package.json, next.config.ts, tailwind, components.json
    └── src/
        ├── app/
        │   ├── login/page.tsx
        │   ├── agents/page.tsx           # 목록 (테이블)
        │   ├── agents/new/page.tsx       # 생성
        │   ├── agents/[id]/page.tsx      # 상세/수정
        │   └── settings/teams/page.tsx   # 팀 관리 (admin)
        ├── components/
        │   ├── agent-form.tsx            # name, description, systemPrompt, icon(emoji), agentType, scope, teams, labels
        │   ├── agent-labels-editor.tsx   # key/value 자동완성 (labels/keys, labels/values)
        │   ├── visibility-selector.tsx   # Personal / Teams / Organization + 팀 multi-select
        │   ├── agents-table.tsx          # 컬럼: Name(+labels), Accessible to, Type, Author, Created, Actions
        │   ├── agents-toolbar.tsx        # 검색, scope/team/label 필터, Active/Deleted 토글
        │   └── delete-agent-dialog.tsx   # soft delete 안내 ("복원 가능")
        └── lib/
            ├── api/client.ts, api/schema.d.ts (generated)
            ├── auth.ts                   # 토큰 저장(localStorage) + 401 시 /login
            └── queries/agents.ts, teams.ts, labels.ts   # useAgentsPaginated, useAgent, useCreateAgent, useUpdateAgent, useDeleteAgent, useRestoreAgent, useLabelKeys, useLabelValues
```

## 데이터 모델 (Alembic 0001)
- `users`
  - 컬럼: id uuid, email unique, name, password_hash, role, created_at
  - role: `admin | member`
- `teams`
  - 컬럼: id, name unique, created_at
- `team_members`
  - 컬럼: team_id, user_id, role
  - role: `member | team_admin`
  - PK는 (team_id, user_id), 둘 다 CASCADE
- `members_settings`
  - 컬럼: user_id PK, default_agent_id
  - default_agent_id는 FK agents ON DELETE SET NULL
- `agents`
  - 기본: id, name, description, system_prompt, icon
  - agent_type: `agent | mcp_gateway`, 기본값 `agent`
  - scope: 기본값 `personal`
  - author_id: FK users ON DELETE SET NULL
  - consider_context_untrusted: bool, 기본값 false
  - created_at, updated_at, deleted_at
  - 인덱스: (scope), (author_id), (agent_type), (deleted_at)
- `agent_teams`
  - PK는 (agent_id, team_id), CASCADE
- `agent_users`
  - 컬럼: agent_id, user_id, level
  - level: `use | write`
  - PK는 (agent_id, user_id)
- `label_keys`, `label_values`
  - 컬럼: id, key/value unique
- `agent_labels`
  - 컬럼: agent_id, key_id, value_id
  - PK는 (agent_id, key_id), 전부 CASCADE

## API
| Method | Path | 설명 |
|---|---|---|
| POST | `/api/auth/login` | email/password → JWT |
| GET | `/api/auth/me` | 사용자 + 팀 목록 |
| GET | `/api/agents` | `name, agentType, scope, teamIds, labels, status, limit, offset, sortBy(name\|createdAt\|team), sortDirection` 지원. 응답은 `{data, pagination:{total, limit, offset, hasNext}}` |
| GET | `/api/agents/{id}` | 접근 가능할 때만 반환, 아니면 404 |
| POST | `/api/agents` | 생성. 검증 규칙은 위 참고 |
| PUT | `/api/agents/{id}` | 부분 수정 |
| DELETE | `/api/agents/{id}` | soft delete |
| POST | `/api/agents/{id}/restore` | 같은 이름 충돌 시 409 |
| DELETE | `/api/agents/{id}/permanent` | 영구 삭제 |
| GET | `/api/agents/labels/keys` · `/api/agents/labels/values?key=` | 자동완성 |
| GET/POST/PUT/DELETE | `/api/teams`, `/api/teams/{id}/members` | 팀 관리 (쓰기는 admin) |
| GET/PUT | `/api/members/default-agent` | 보이는 agent만 지정할 수 있다 |

읽기 응답 `AgentRead`는 agent 컬럼에 `teams[{id,name}]`, `labels[{key,value}]`(key 순 정렬), `authorName`을 더한 것이다. 목록 조회는 teams/labels/author를 batch로 로드해서 N+1을 막는다.

## 구현 순서
1. 저장소 골격: docker-compose, Makefile(`make up`, `make migrate`, `make seed`, `make test`, `make gen-api`), .env.example
2. Backend 기반: config, db, errors, ORM 모델, Alembic 초기 migration
3. 인증, seed, teams API
4. repositories, `services/access.py`, `services/agent.py`, `api/agents.py`, members API
5. Backend 테스트(접근제어 매트릭스, scope 검증, 라벨 sync/필터, soft delete/restore 409, default-agent 해제)
6. Frontend 기반: Next.js, shadcn, TanStack Query provider, openapi 타입 생성, 로그인
7. Agents 목록(필터/정렬/페이지네이션, Active/Deleted), 생성/수정 폼, 삭제/복원, 팀 설정 페이지
8. README: 실행 방법과 Archestra 대응표

## 검증
- `make up && make migrate && make seed` 후 다음을 확인한다.
  - `http://localhost:8000/docs`에서 OpenAPI 확인
  - `http://localhost:3000`에서 admin과 member로 각각 로그인
- `make test` (pytest)가 통과해야 한다. 핵심 케이스는 다음과 같다.
  - member는 다른 사람의 personal agent를 보지 못한다(목록 미포함, 단건 조회 404).
  - member가 org scope로 생성하면 403이다. 속하지 않은 팀을 지정하면 403이다.
  - team scope인데 teams가 비어 있으면 400이다. team/org를 personal로 바꾸면 400이다.
  - `labels=env:prod|dev;owner:a` 필터가 AND/OR 의미로 동작한다.
  - 삭제 후 restore할 때 같은 이름의 활성 agent가 있으면 409이다.
- Frontend: `pnpm lint && pnpm build`가 통과해야 한다. 브라우저에서 생성 → 라벨 추가 → 팀 공유 → member 계정에서 보이는지 → 삭제 → Deleted 탭에서 복원까지 수동으로 확인한다.

## 구현 중 변경사항
- **Next.js 16**: `create-next-app@latest`가 16.4를 설치했다.
  - `cacheComponents`가 기본으로 켜져 있어서, 페이지는 얇은 server component로 두고 client component를 렌더링한다.
  - `useSearchParams`/`useParams` 때문에 root layout에 `<Suspense>`를 둔다.
- **shadcn/ui**: 현재 기본 스타일(`base-nova`)은 Radix가 아니라 **Base UI** 기반이다(`render` prop 사용).
  - shadcn이 추가한 `cn` 패키지는 0.5.0이 배포 4일차라서 Archestra의 7일 규칙에 맞춰 `0.4.0`으로 고정했다.
- **인증**: `passlib` 대신 `bcrypt`를 직접 사용한다.
- **API 추가**
  - `GET /api/agents/all`: agent 선택용 전체 목록
  - `GET/POST /api/users`: 사용자 목록, admin의 사용자 생성
- **공유 권한**: `agent_users.level = write`면 personal agent를 수정할 수 있다. Archestra는 작성자만 가능하므로 이 부분은 확장이다.
- **영구 삭제**: soft delete된 agent만 가능하다(그 외 400).
- **포트**: `FRONTEND_PORT`로 frontend 호스트 포트를 바꿀 수 있다(CORS도 함께 바뀐다).
- **테이블 이름**: `members_settings` → `member_settings`
