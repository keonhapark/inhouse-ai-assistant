package io.inhouse.erp.org;

import java.time.LocalDate;
import java.util.List;

/** 계약(erp.yaml)의 조직 응답 형태입니다. */
public final class OrgViews {

    private OrgViews() {}

    public record EmployeeSummary(String id, String name, String unitId, String unitName, String grade) {}

    public record EmployeeFull(String id, String name, String unitId, String unitName, String grade,
                               String employeeNo, String email, List<String> roles, LocalDate hiredOn) {}

    public record UnitView(String id, String name, String kind, String parentId, String headId) {}

    public record AccessTags(String employeeId, List<String> tags) {}

    public record Items<T>(List<T> items) {}
}
