package io.inhouse.erp.pack;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 업종 팩(PACK_DIR)에서 읽은 설정과 고정 데이터입니다. erp 코어는 업종 용어를 코드에 두지 않고 이것만 봅니다.
 */
public record Pack(
        String id,
        ZoneId timezone,
        List<Grade> grades,
        List<UnitDef> units,
        List<RoleDef> roles,
        List<AccessTagDef> accessTags,
        DelegationPolicy delegationPolicy,
        List<FormDef> forms,
        List<EmployeeDef> employees,
        List<RoomDef> rooms,
        List<BalanceDef> balances) {

    public record Grade(String id, String name, int rank) {}

    public record UnitDef(String id, String name, String kind, String parent) {}

    public record RoleDef(String id, String name, Grant grant) {}

    public record AccessTagDef(String id, String name, Grant grant) {}

    public record DelegationPolicy(int maxPeriodDays, List<String> registrableBy) {}

    public record FormDef(String id, String name, JsonNode fields, String amountField,
                          Map<String, String> effects, List<LineRule> approvalLine) {}

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
