package io.inhouse.erp.approval;

import java.util.List;

/**
 * 결재 대결 규칙과 결재 엔진의 경계. 대리인이 결재할 수 있는지, 대리인이 문서를 볼 수 있는지,
 * 대결로 지금 결재할 문서는 무엇인지를 대결 모듈이 답합니다.
 */
public interface DelegateAuthority {

    /**
     * actor가 approver 대신 doc의 현재 단계를 결재할 수 있으면 위임 ID를 돌려줍니다.
     * 안 되면 이유에 맞는 오류를 던집니다(기간 밖, 범위 밖, 해지, 재위임, 결재선에 없음 등).
     */
    String authorize(ApprovalDocument doc, String approverId, String actorId);

    /** 결재선 결재자의 유효한 대리인이면 문서를 볼 수 있습니다. */
    boolean canView(ApprovalDocument doc, String employeeId);

    /** 대결로 지금 employeeId가 결재할 수 있는 진행 중 문서. */
    List<ApprovalDocument> delegatedInbox(String employeeId);
}
