-- 결재 대결 위임(직원 → 직원, 기간 단위)
create table delegation (
    id            varchar(32) primary key,
    delegator_id  varchar(32)  not null references employee (id),
    delegate_id   varchar(32)  not null references employee (id),
    starts_at     timestamptz  not null,
    ends_at       timestamptz  not null,
    form_types    jsonb        not null,
    max_amount    bigint,
    reason        varchar(200) not null,
    registered_by varchar(32)  not null references employee (id),
    revoked_at    timestamptz,
    revoked_by    varchar(32),
    created_at    timestamptz  not null,
    check (starts_at < ends_at),
    check (delegator_id <> delegate_id)
);
create index delegation_delegator on delegation (delegator_id);
create index delegation_delegate on delegation (delegate_id);
create index approval_step_delegation on approval_step (delegation_id);
