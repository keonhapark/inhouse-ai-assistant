package io.inhouse.erp.approval;

import io.inhouse.erp.common.ApiException;
import java.util.List;
import org.springframework.stereotype.Component;

/** 대결 모듈(#6)이 들어오기 전의 기본값: 원 결재자만 결재합니다. */
@Component
class NoDelegation implements DelegateAuthority {

    @Override
    public String authorize(ApprovalDocument doc, String approverId, String actorId) {
        if (doc.getSteps().stream().anyMatch(s -> s.getApproverId().equals(actorId))) {
            throw new ApiException(403, "not-current-approver", "현재 결재 차례가 아닙니다");
        }
        throw ApiException.notFound("결재 문서가 없습니다");
    }

    @Override
    public boolean canView(ApprovalDocument doc, String employeeId) {
        return false;
    }

    @Override
    public List<ApprovalDocument> delegatedInbox(String employeeId) {
        return List.of();
    }
}
