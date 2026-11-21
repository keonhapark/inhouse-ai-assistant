package io.inhouse.erp.org;

import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.org.OrgViews.EmployeeFull;
import io.inhouse.erp.org.OrgViews.EmployeeSummary;
import io.inhouse.erp.org.OrgViews.UnitView;
import io.inhouse.erp.pack.Pack;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class OrgService {

    private final EmployeeRepository employees;
    private final OrgUnitRepository units;
    private final OrgPolicy policy;
    private final Pack.ErpRoles roles;

    public OrgService(EmployeeRepository employees, OrgUnitRepository units, OrgPolicy policy, Pack pack) {
        this.employees = employees;
        this.units = units;
        this.policy = policy;
        this.roles = pack.erpRoles();
    }

    /** 인사 담당(팩 erp_roles.hr). 직원 상세 전체 필드, 다른 사람의 연차 잔여를 봅니다. */
    public boolean isHr(String employeeId) {
        return hasRole(employeeId, roles.hr());
    }

    /** IT 티켓 담당(팩 erp_roles.ticket_handler). 전체 티켓 조회, 상태 변경. */
    public boolean isTicketHandler(String employeeId) {
        return hasRole(employeeId, roles.ticketHandler());
    }

    /** 품질 확인(팩 erp_roles.quality_reviewer). 전체 불량 보고서 조회, 확정. */
    public boolean isQualityReviewer(String employeeId) {
        return hasRole(employeeId, roles.qualityReviewer());
    }

    /** 영업(팩 erp_roles.sales_rep). 견적 작성·전체 조회·발행, 고객사 연락처. */
    public boolean isSalesRep(String employeeId) {
        return hasRole(employeeId, roles.salesRep());
    }

    /** 감사 조회(팩 erp_roles.auditor). */
    public boolean isAuditor(String employeeId) {
        return hasRole(employeeId, roles.auditor());
    }

    public Employee employee(String id) {
        return employees.findById(id).orElseThrow(() -> ApiException.notFound("직원 " + id + "가 없습니다"));
    }

    public boolean hasRole(String employeeId, String role) {
        return employees.findById(employeeId).map(e -> e.hasRole(role)).orElse(false);
    }

    public List<UnitView> units() {
        return units.findAllByOrderBySortOrder().stream()
                .map(u -> new UnitView(u.getId(), u.getName(), u.getKind(), u.getParentId(), u.getHeadId()))
                .toList();
    }

    public List<EmployeeSummary> search(String q, String unitId, int limit) {
        Map<String, String> names = unitNames();
        return employees.search(blankToNull(q), blankToNull(unitId), Limit.of(Math.max(1, Math.min(limit, 100))))
                .stream().map(e -> summary(e, names)).toList();
    }

    /** 본인과 인사 담당은 전체 필드, 그 밖에는 공개 필드만 봅니다. */
    public Object view(String viewerId, String employeeId) {
        Employee target = employee(employeeId);
        if (viewerId.equals(employeeId) || isHr(viewerId)) {
            return full(target);
        }
        return summary(target, unitNames());
    }

    public EmployeeFull full(Employee e) {
        String unitName = units.findById(e.getUnitId()).map(OrgUnit::getName).orElse(e.getUnitId());
        return new EmployeeFull(e.getId(), e.getName(), e.getUnitId(), unitName, e.getGrade(), e.getEmployeeNo(),
                e.getEmail(), e.getRoles(), e.getHiredOn());
    }

    public List<String> accessTags(String employeeId) {
        return policy.accessTagsOf(employee(employeeId));
    }

    private EmployeeSummary summary(Employee e, Map<String, String> unitNames) {
        return new EmployeeSummary(e.getId(), e.getName(), e.getUnitId(),
                unitNames.getOrDefault(e.getUnitId(), e.getUnitId()), e.getGrade());
    }

    private Map<String, String> unitNames() {
        return units.findAll().stream().collect(Collectors.toMap(OrgUnit::getId, OrgUnit::getName,
                (a, b) -> a));
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s;
    }
}
