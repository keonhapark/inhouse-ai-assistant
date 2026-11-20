-- IT 티켓. 상태 변경은 이력 행을 남겨 되돌리기 때 이전 상태로 돌아갑니다.
create table ticket (
    id           varchar(32)   primary key,
    requester_id varchar(32)   not null references employee (id),
    category     varchar(32)   not null check (category in ('incident', 'access_request', 'other')),
    priority     varchar(16)   not null check (priority in ('low', 'normal', 'high')),
    title        varchar(100)  not null,
    description  varchar(2000) not null,
    status       varchar(16)   not null check (status in ('open', 'in_progress', 'resolved', 'closed', 'cancelled')),
    version      int           not null default 0,
    created_at   timestamptz   not null,
    updated_at   timestamptz   not null
);
create index ticket_requester on ticket (requester_id, updated_at desc);
create index ticket_updated on ticket (updated_at desc);

create table ticket_comment (
    id         varchar(32)   primary key,
    ticket_id  varchar(32)   not null references ticket (id),
    author_id  varchar(32)   not null references employee (id),
    body       varchar(2000) not null,
    created_at timestamptz   not null
);
create index ticket_comment_ticket on ticket_comment (ticket_id, created_at);

create table ticket_status_change (
    id            varchar(32) primary key,
    ticket_id     varchar(32) not null references ticket (id),
    from_status   varchar(16) not null check (from_status in ('open', 'in_progress', 'resolved', 'closed', 'cancelled')),
    to_status     varchar(16) not null check (to_status in ('open', 'in_progress', 'resolved', 'closed', 'cancelled')),
    version_after int         not null check (version_after >= 1),
    changed_by    varchar(32) not null references employee (id),
    changed_at    timestamptz not null
);
create index ticket_status_change_ticket on ticket_status_change (ticket_id);
