-- 회의실 예약. 같은 회의실의 겹치는 확정 예약은 배제 제약으로 막습니다(동시 요청 둘 중 하나만 성공).
create extension if not exists btree_gist;

create table room_reservation (
    id          varchar(32) primary key,
    room_id     varchar(64)  not null references room (id),
    reserved_by varchar(32)  not null references employee (id),
    starts_at   timestamptz  not null,
    ends_at     timestamptz  not null,
    title       varchar(100) not null,
    attendees   int,
    status      varchar(16)  not null check (status in ('confirmed', 'cancelled')),
    check (starts_at < ends_at),
    constraint room_reservation_no_overlap
        exclude using gist (room_id with =, tstzrange(starts_at, ends_at) with &&) where (status = 'confirmed')
);
create index room_reservation_reserved_by on room_reservation (reserved_by, starts_at);
