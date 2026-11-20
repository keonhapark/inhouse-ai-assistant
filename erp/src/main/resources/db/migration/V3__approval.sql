-- 결재 문서와 결재선 단계, 알림
create table approval_document (
    id            varchar(32) primary key,
    form_id       varchar(64)  not null references approval_form (id),
    title         varchar(100) not null,
    requester_id  varchar(32)  not null references employee (id),
    status        varchar(16)  not null check (status in ('in_progress', 'approved', 'rejected', 'withdrawn')),
    fields        jsonb        not null,
    amount        bigint,
    current_step  int,
    leave_days    numeric(5, 1) not null default 0,
    version       int          not null,
    created_at    timestamptz  not null,
    updated_at    timestamptz  not null
);
create index approval_document_requester on approval_document (requester_id, created_at desc);

create table approval_step (
    document_id   varchar(32) not null references approval_document (id),
    step_order    int         not null,
    approver_id   varchar(32) not null references employee (id),
    status        varchar(16) not null check (status in ('waiting', 'pending', 'approved', 'rejected', 'skipped')),
    acted_by      varchar(32),
    on_behalf_of  varchar(32),
    delegation_id varchar(32),
    acted_at      timestamptz,
    comment       varchar(200),
    primary key (document_id, step_order)
);
create index approval_step_approver on approval_step (approver_id);
create index approval_step_acted_by on approval_step (acted_by);

create table notification (
    id            varchar(32) primary key,
    recipient_id  varchar(32)  not null,
    kind          varchar(32)  not null,
    message       varchar(300) not null,
    document_id   varchar(32),
    delegation_id varchar(32),
    created_at    timestamptz  not null,
    read          boolean      not null default false
);
create index notification_recipient on notification (recipient_id, created_at);
