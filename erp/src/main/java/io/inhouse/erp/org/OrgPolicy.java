package io.inhouse.erp.org;

import io.inhouse.erp.pack.Pack;
import java.util.List;
import org.springframework.stereotype.Component;

/** 팩의 grant 규칙으로 역할과 문서 접근 태그를 정합니다. */
@Component
public class OrgPolicy {

    private final Pack pack;

    public OrgPolicy(Pack pack) {
        this.pack = pack;
    }

    public List<String> rolesOf(String unitId, String grade) {
        return pack.roles().stream()
                .filter(r -> r.grant().matches(unitId, grade, List.of()))
                .map(Pack.RoleDef::id)
                .toList();
    }

    public List<String> accessTagsOf(Employee e) {
        return pack.accessTags().stream()
                .filter(t -> t.grant().matches(e.getUnitId(), e.getGrade(), e.getRoles()))
                .map(Pack.AccessTagDef::id)
                .toList();
    }
}
