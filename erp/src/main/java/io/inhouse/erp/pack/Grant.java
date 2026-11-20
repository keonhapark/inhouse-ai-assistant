package io.inhouse.erp.pack;

import java.util.Collection;
import java.util.Set;

/**
 * 팩의 grant 규칙(org.yaml roles·access_tags). {@code all}이거나, 조직·직급·역할 중 하나가 맞으면 부여합니다.
 */
public record Grant(boolean all, Set<String> units, Set<String> grades, Set<String> roles) {

    public static final Grant ALL = new Grant(true, Set.of(), Set.of(), Set.of());

    public boolean matches(String unitId, String grade, Collection<String> employeeRoles) {
        if (all || units.contains(unitId) || grades.contains(grade)) {
            return true;
        }
        return employeeRoles != null && employeeRoles.stream().anyMatch(roles::contains);
    }
}
