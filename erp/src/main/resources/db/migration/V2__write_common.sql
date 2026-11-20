-- 쓰기 공통: 실행한 행동(되돌리기), 멱등 키(24시간), 감사 이벤트
create table action (
    id                    varchar(32) primary key,
    operation             varchar(64)  not null,
    actor_id              varchar(32)  not null,
    via_delegation_token  boolean      not null,
    agent_id              varchar(64),
    conversation_id       varchar(128),
    resource_type         varchar(64)  not null,
    resource_id           varchar(64)  not null,
    status                varchar(16)  not null check (status in ('done', 'undone')),
    undoable              boolean      not null,
    undo_action_id        varchar(32),
    created_at            timestamptz  not null
);
create index action_actor on action (actor_id);

create table idempotency_record (
    owner_id      varchar(32)  not null,
    idem_key      varchar(128) not null,
    request_hash  varchar(64)  not null,
    status        int          not null,
    response      jsonb        not null,
    created_at    timestamptz  not null,
    primary key (owner_id, idem_key)
);
create index idempotency_record_created on idempotency_record (created_at);

create table audit_event (
    seq          bigserial primary key,
    event_id     varchar(32)  not null unique,
    occurred_at  timestamptz  not null,
    actor_id     varchar(32),
    action_id    varchar(32),
    kind         varchar(64)  not null,
    event        jsonb        not null
);
create index audit_event_actor on audit_event (actor_id);
create index audit_event_action on audit_event (action_id);
