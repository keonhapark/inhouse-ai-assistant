package io.inhouse.erp.delegation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.notification.Notifications;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.EmployeeRepository;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Set;
import java.util.function.BooleanSupplier;
import java.util.stream.Collectors;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 결재 대결 위임의 등록·해지·조회. 등록 규칙은 팩 org.yaml의 delegation_policy를 따릅니다.
 * 쓰기 메서드는 WriteExecutor의 트랜잭션 안에서 불립니다.
 */
@Service
public class DelegationService {

    public record ScopeView(List<String> formTypes, Long maxAmount) {}

    public record DelegationView(String id, String delegatorId, String delegateId, OffsetDateTime startsAt,
                                 OffsetDateTime endsAt, ScopeView scope, String reason, String status,
                                 String registeredBy, OffsetDateTime revokedAt, String revokedBy,
                                 OffsetDateTime createdAt) {}

    /** 등록 요청(계약 DelegationCreate). */
    public record CreateRequest(String delegatorId, String delegateId, OffsetDateTime startsAt, OffsetDateTime endsAt,
                                List<String> formTypes, Long maxAmount, String reason) {}

    private static final DateTimeFormatter DAY_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    private final DelegationRepository repo;
    private final EmployeeRepository employees;
    private final OrgService org;
    private final Notifications notifications;
    private final Pack pack;
    private final Set<String> formIds;
    private final ObjectMapper mapper;
    private final Clock clock;

    public DelegationService(DelegationRepository repo, EmployeeRepository employees, OrgService org,
                             Notifications notifications, Pack pack, ObjectMapper mapper, Clock clock) {
        this.repo = repo;
        this.employees = employees;
        this.org = org;
        this.notifications = notifications;
        this.pack = pack;
        this.formIds = pack.forms().stream().map(Pack.FormDef::id).collect(Collectors.toUnmodifiableSet());
        this.mapper = mapper;
        this.clock = clock;
    }

    // ---------- 등록 ----------

    /**
     * 위임자 본인이 하거나, 팩이 허용한 역할(registrable_by, 예: 인사 담당)이 delegatorId를 지정해 합니다.
     * 위임자가 결재선에 없는 사람이어도 등록은 됩니다.
     */
    public WriteOutcome create(ErpPrincipal p, CreateRequest req) {
        String delegator = req.delegatorId() == null ? p.employeeId() : req.delegatorId();
        if (!delegator.equals(p.employeeId()) && !canRegisterForOthers(p.employeeId())) {
            throw new ApiException(403, "delegation-registrar-forbidden", "위임자 본인이나 등록 권한이 있는 역할만 등록합니다");
        }
        if (!employees.existsById(delegator)) {
            throw ApiException.validation("delegatorId", "unknown");
        }
        if (req.delegateId() == null || !employees.existsById(req.delegateId())) {
            throw ApiException.validation("delegateId", "unknown");
        }
        if (req.delegateId().equals(delegator)) {
            throw new ApiException(422, "delegation-self", "본인에게 위임할 수 없습니다");
        }
        OffsetDateTime now = OffsetDateTime.now(clock);
        if (!req.startsAt().isBefore(req.endsAt())) {
            throw ApiException.validation("endsAt", "시작이 끝보다 앞이어야 합니다");
        }
        if (!req.endsAt().isAfter(now)) {
            throw ApiException.validation("endsAt", "끝이 이미 지났습니다");
        }
        int maxDays = pack.delegationPolicy().maxPeriodDays();
        if (Duration.between(req.startsAt(), req.endsAt()).compareTo(Duration.ofDays(maxDays)) > 0) {
            throw new ApiException(422, "delegation-period-too-long", "최대 " + maxDays + "일입니다");
        }
        List<String> types = req.formTypes();
        if (types == null || types.isEmpty()
                || types.stream().anyMatch(t -> !Delegation.ALL_FORMS.equals(t) && !formIds.contains(t))) {
            throw ApiException.validation("scope.formTypes", "unknown form");
        }
        Delegation d = repo.saveAndFlush(new Delegation(Ids.next("dlg"), delegator, req.delegateId(), req.startsAt(),
                req.endsAt(), types, req.maxAmount(), req.reason(), p.employeeId(), now));
        String delegatorName = name(delegator);
        String period = local(d.getStartsAt()) + " ~ " + local(d.getEndsAt());
        notifications.send(req.delegateId(), Notifications.DELEGATION_REGISTERED,
                delegatorName + "님의 결재 대결을 맡았습니다(" + period + ")", null, d.getId());
        DelegationView view = view(d);
        return WriteOutcome.of(delegatorName + "님의 결재를 " + name(req.delegateId()) + "님이 대신합니다(" + period
                        + ", 양식 " + String.join(", ", types) + ")",
                new Change("create", "delegation", d.getId(), null, json(view)), true, view, d.getId())
                .withDelegation(null, d.getId());
    }

    /** 등록 되돌리기: 해지와 같습니다. 이 위임으로 이미 결재한 문서가 있으면 409입니다. */
    public WriteOutcome undoCreate(String delegationId, String by, BooleanSupplier used) {
        Delegation d = repo.lockById(delegationId).orElseThrow();
        if (used.getAsBoolean()) {
            throw new ApiException(409, "undo-conflict", "이 위임으로 이미 결재한 문서가 있습니다");
        }
        if (d.getRevokedAt() != null) {
            throw new ApiException(409, "undo-conflict", "이미 해지된 위임입니다");
        }
        JsonNode before = json(view(d));
        d.revoke(by, OffsetDateTime.now(clock));
        DelegationView after = view(repo.saveAndFlush(d));
        return WriteOutcome.of("대결 위임 등록을 되돌렸습니다", new Change("update", "delegation", d.getId(), before,
                json(after)), false, after, d.getId()).withDelegation(null, d.getId());
    }

    // ---------- 해지 ----------

    /** 위임자 본인이나 인사 담당만 해지합니다. 이미 해지됐거나 끝났으면 409입니다. */
    public WriteOutcome revoke(ErpPrincipal p, String delegationId) {
        Delegation d = repo.lockById(delegationId).filter(x -> canSee(p.employeeId(), x))
                .orElseThrow(() -> ApiException.notFound("위임이 없습니다"));
        if (!p.employeeId().equals(d.getDelegatorId()) && !org.hasRole(p.employeeId(), OrgService.HR_ROLE)) {
            throw ApiException.forbidden("위임자 본인이나 인사 담당만 해지합니다");
        }
        OffsetDateTime now = OffsetDateTime.now(clock);
        String status = d.status(now);
        if (status.equals("revoked") || status.equals("expired")) {
            throw new ApiException(409, "invalid-state", "이미 " + status + "입니다");
        }
        JsonNode before = json(view(d));
        d.revoke(p.employeeId(), now);
        DelegationView after = view(repo.saveAndFlush(d));
        return WriteOutcome.of("대결 위임을 해지합니다", new Change("update", "delegation", d.getId(), before,
                json(after)), false, after, d.getId()).withDelegation(null, d.getId());
    }

    // ---------- 조회 ----------

    @Transactional(readOnly = true)
    public List<DelegationView> list(String employeeId, String role, OffsetDateTime activeAt) {
        List<Delegation> rows = switch (role) {
            case "delegator" -> repo.findByDelegatorIdOrderByCreatedAtDesc(employeeId);
            case "delegate" -> repo.findByDelegateIdOrderByCreatedAtDesc(employeeId);
            case "all" -> {
                if (!org.hasRole(employeeId, OrgService.HR_ROLE)) {
                    throw ApiException.forbidden("인사 담당만 전체를 봅니다");
                }
                yield repo.findAllByOrderByCreatedAtDesc();
            }
            default -> throw ApiException.validation("role", "delegator, delegate, all 중 하나");
        };
        return rows.stream()
                .filter(d -> activeAt == null || (d.getRevokedAt() == null && !activeAt.isBefore(d.getStartsAt())
                        && !activeAt.isAfter(d.getEndsAt())))
                .map(this::view).toList();
    }

    /** 위임자, 대리인, 등록한 사람, 인사 담당만 봅니다. 그 밖에는 404입니다. */
    @Transactional(readOnly = true)
    public Delegation visible(String employeeId, String delegationId) {
        return repo.findById(delegationId).filter(d -> canSee(employeeId, d))
                .orElseThrow(() -> ApiException.notFound("위임이 없습니다"));
    }

    public DelegationView view(Delegation d) {
        ZoneId zone = pack.timezone();
        return new DelegationView(d.getId(), d.getDelegatorId(), d.getDelegateId(), at(d.getStartsAt(), zone),
                at(d.getEndsAt(), zone), new ScopeView(d.getFormTypes(), d.getMaxAmount()), d.getReason(),
                d.status(OffsetDateTime.now(clock)), d.getRegisteredBy(), at(d.getRevokedAt(), zone),
                d.getRevokedBy(), at(d.getCreatedAt(), zone));
    }

    private boolean canSee(String employeeId, Delegation d) {
        return employeeId.equals(d.getDelegatorId()) || employeeId.equals(d.getDelegateId())
                || employeeId.equals(d.getRegisteredBy()) || org.hasRole(employeeId, OrgService.HR_ROLE);
    }

    private boolean canRegisterForOthers(String employeeId) {
        Employee e = org.employee(employeeId);
        return pack.delegationPolicy().registrableBy().stream()
                .filter(r -> !"self".equals(r))
                .anyMatch(e::hasRole);
    }

    private String name(String employeeId) {
        return org.employee(employeeId).getName();
    }

    private String local(OffsetDateTime t) {
        return t.atZoneSameInstant(pack.timezone()).format(DAY_TIME);
    }

    private static OffsetDateTime at(OffsetDateTime t, ZoneId zone) {
        return t == null ? null : t.atZoneSameInstant(zone).toOffsetDateTime();
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }
}
