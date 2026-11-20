package io.inhouse.erp.approval;

import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.OrgUnit;
import io.inhouse.erp.org.OrgUnitRepository;
import io.inhouse.erp.pack.Pack;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

/**
 * 팩 양식의 결재선 규칙(approval_line)을 실제 결재자 목록으로 풉니다(org.yaml approver_resolution).
 * <ul>
 *   <li>team_leader: 요청자 팀의 팀장. 요청자가 팀장이거나 팀이 아니면 division_head로</li>
 *   <li>division_head: 요청자 본부의 본부장. 요청자가 본부장이거나 본부장이 없으면 대표이사</li>
 *   <li>ceo: 최상위 조직의 장</li>
 * </ul>
 * 요청자 본인과 이미 들어간 결재자는 빼므로, 대표이사가 올린 문서는 결재선이 비어 바로 승인됩니다.
 */
@Component
public class ApprovalLineResolver {

    private final OrgUnitRepository units;

    public ApprovalLineResolver(OrgUnitRepository units) {
        this.units = units;
    }

    public List<String> resolve(Pack.FormDef form, Employee requester, Long amount) {
        Map<String, OrgUnit> byId = units.findAll().stream().collect(Collectors.toMap(OrgUnit::getId, Function.identity()));
        for (Pack.LineRule rule : form.approvalLine()) {
            if (!rule.matches(amount)) {
                continue;
            }
            List<String> line = new ArrayList<>();
            for (String step : rule.steps()) {
                String approver = approver(step, requester, byId);
                if (approver != null && !approver.equals(requester.getId()) && !line.contains(approver)) {
                    line.add(approver);
                }
            }
            return line;
        }
        throw new ApiException(422, "form-validation-failed", "맞는 결재선 규칙이 없습니다");
    }

    private String approver(String step, Employee requester, Map<String, OrgUnit> byId) {
        OrgUnit unit = byId.get(requester.getUnitId());
        switch (step) {
            case "ceo":
                return rootHead(byId);
            case "team_leader":
                if (unit.isTeam() && unit.getHeadId() != null && !unit.getHeadId().equals(requester.getId())) {
                    return unit.getHeadId();
                }
                return divisionHead(requester, unit, byId);
            case "division_head":
                return divisionHead(requester, unit, byId);
            default:
                throw new IllegalStateException("팩의 결재선 단계가 알 수 없는 값입니다: " + step);
        }
    }

    private String divisionHead(Employee requester, OrgUnit unit, Map<String, OrgUnit> byId) {
        OrgUnit division = unit.isTeam() ? byId.getOrDefault(unit.getParentId(), unit) : unit;
        String head = division.getHeadId();
        if (head == null || head.equals(requester.getId())) {
            String ceo = rootHead(byId);
            return requester.getId().equals(ceo) ? null : ceo;
        }
        return head;
    }

    private static String rootHead(Map<String, OrgUnit> byId) {
        return byId.values().stream().filter(u -> u.getParentId() == null).map(OrgUnit::getHeadId)
                .findFirst().orElse(null);
    }
}
