-- 조직·직원·양식·회의실·연차 잔여. 팩(PACK_DIR)에서 적재합니다.
create table org_unit (
    id         varchar(64) primary key,
    name       varchar(100) not null,
    kind       varchar(16)  not null check (kind in ('division', 'team')),
    parent_id  varchar(64) references org_unit (id),
    head_id    varchar(32),
    sort_order int          not null
);

create table employee (
    id          varchar(32) primary key,
    employee_no varchar(32)  not null unique,
    name        varchar(100) not null,
    unit_id     varchar(64)  not null references org_unit (id),
    grade       varchar(32)  not null,
    email       varchar(200) not null,
    hired_on    date         not null
);

create table employee_role (
    employee_id varchar(32) not null references employee (id),
    role_id     varchar(32) not null,
    sort_order  int         not null,
    primary key (employee_id, role_id)
);

create table approval_form (
    id            varchar(64) primary key,
    name          varchar(100) not null,
    fields_schema jsonb        not null,
    amount_field  varchar(64),
    sort_order    int          not null
);

create table room (
    id       varchar(64) primary key,
    name     varchar(100) not null,
    floor    int          not null,
    capacity int          not null
);

create table leave_balance (
    employee_id    varchar(32) not null references employee (id),
    year           int         not null,
    annual_total   numeric(5, 1) not null,
    annual_used    numeric(5, 1) not null,
    annual_pending numeric(5, 1) not null default 0,
    primary key (employee_id, year)
);
