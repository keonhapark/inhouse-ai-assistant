package io.inhouse.erp.pack;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 업종 팩(PACK_DIR)에서 읽은 설정과 고정 데이터입니다. erp 코어는 업종 용어를 코드에 두지 않고 이것만 봅니다.
 */
public record Pack(
        String id,
        int stage,
        ZoneId timezone,
        List<Grade> grades,
        List<UnitDef> units,
        List<RoleDef> roles,
        List<AccessTagDef> accessTags,
        ErpRoles erpRoles,
        DelegationPolicy delegationPolicy,
        List<FormDef> forms,
        List<EmployeeDef> employees,
        List<RoomDef> rooms,
        List<BalanceDef> balances,
        List<TicketDef> tickets) {

    public record Grade(String id, String name, int rank) {}

    public record UnitDef(String id, String name, String kind, String parent) {}

    public record RoleDef(String id, String name, Grant grant) {}

    public record AccessTagDef(String id, String name, Grant grant) {}

    /** org.yaml erp_roles: 코어가 권한 판단에 쓰는 역할 ID. 항목이 없으면 hr_staff·auditor입니다. */
    public record ErpRoles(String hr, String auditor, String ticketHandler) {
        public static final ErpRoles DEFAULT = new ErpRoles("hr_staff", "auditor", "it_admin");
    }

    public record DelegationPolicy(int maxPeriodDays, List<String> registrableBy) {}

    /** amountProductOf: 금액 필드가 이 정수 필드들의 곱과 같아야 합니다(팩 amount_product_of, 없으면 빈 목록). */
    public record FormDef(String id, String name, int stage, JsonNode fields, String amountField,
                          List<String> amountProductOf, Map<String, String> effects, List<LineRule> approvalLine) {}

    /** 양식 중 stage가 maxStage 이하인 것만 켠 팩. 나머지 설정과 고정 데이터는 그대로입니다. */
    public Pack withFormsUpTo(int maxStage) {
        return new Pack(id, stage, timezone, grades, units, roles, accessTags, erpRoles, delegationPolicy,
                forms.stream().filter(f -> f.stage() <= maxStage).toList(), employees, rooms, balances, tickets);
    }


    /** 결재선 규칙 하나. 조건(when)이 맞으면 steps의 결재자 해석 규칙을 차례로 씁니다. */
    public record LineRule(Long amountLte, Long amountGt, List<String> steps) {
        public boolean matches(Long amount) {
            if (amountLte != null && (amount == null || amount > amountLte)) {
                return false;
            }
            return amountGt == null || (amount != null && amount > amountGt);
        }
    }

    public record EmployeeDef(String id, String employeeNo, String name, String unitId, String grade,
                              String email, LocalDate hiredOn) {}

    public record RoomDef(String id, String name, int floor, int capacity) {}

    public record BalanceDef(String employeeId, int year, double annualTotal, double annualUsed) {}

    /** 선택 파일 fixtures/tickets.json의 지어낸 IT 티켓. */
    public record TicketDef(String id, String requesterId, String category, String priority, String title,
                            String description, String status, OffsetDateTime createdAt, List<CommentDef> comments) {}

    public record CommentDef(String authorId, String body, OffsetDateTime createdAt) {}

    public Optional<UnitDef> unit(String id) {
        return units.stream().filter(u -> u.id().equals(id)).findFirst();
    }

    /** 직급 rank가 2 이상(조직장)인지. 팩의 grades 순서로 판단합니다. */
    public boolean isHeadGrade(String gradeId) {
        return grades.stream().anyMatch(g -> g.id().equals(gradeId) && g.rank() > lowestRank());
    }

    private int lowestRank() {
        return grades.stream().mapToInt(Grade::rank).min().orElse(0);
    }
}
