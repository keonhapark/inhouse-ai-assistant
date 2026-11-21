-- 불량 보고서와 견적. 품목·고객사는 팩 고정 데이터라 메모리에서 읽고 표에는 코드·이름만 남깁니다.
create table defect_report (
    id           varchar(32)   primary key,
    created_by   varchar(32)   not null references employee (id),
    item_code    varchar(32)   not null,
    item_name    varchar(100)  not null,
    defect_type  varchar(50)   not null,
    severity     varchar(16)   not null check (severity in ('minor', 'major', 'critical')),
    quantity     int           not null check (quantity >= 1),
    location     varchar(100),
    lot_no       varchar(50),
    description  varchar(1000) not null,
    status       varchar(16)   not null check (status in ('draft', 'confirmed', 'cancelled')),
    version      int           not null default 0,
    confirmed_by varchar(32)   references employee (id),
    created_at   timestamptz   not null,
    updated_at   timestamptz   not null
);
create index defect_report_created_by on defect_report (created_by, created_at desc);
create index defect_report_created on defect_report (created_at desc);

create table quote (
    id            varchar(32)  primary key,
    created_by    varchar(32)  not null references employee (id),
    customer_id   varchar(32)  not null,
    customer_name varchar(100) not null,
    lines         jsonb        not null,
    total_amount  bigint       not null check (total_amount >= 0),
    valid_until   date         not null,
    note          varchar(500),
    status        varchar(16)  not null check (status in ('draft', 'issued', 'cancelled')),
    version       int          not null default 0,
    issued_by     varchar(32)  references employee (id),
    created_at    timestamptz  not null,
    updated_at    timestamptz  not null
);
create index quote_created_by on quote (created_by, created_at desc);
create index quote_created on quote (created_at desc);
