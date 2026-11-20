package io.inhouse.erp.delegation;

import io.inhouse.erp.approval.ApprovalDocumentRepository;
import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import org.springframework.stereotype.Component;

@Component
class CreateDelegationUndo implements UndoHandler {

    private final DelegationService delegations;
    private final ApprovalDocumentRepository docs;

    CreateDelegationUndo(DelegationService delegations, ApprovalDocumentRepository docs) {
        this.delegations = delegations;
        this.docs = docs;
    }

    @Override
    public String operation() {
        return "createDelegation";
    }

    @Override
    public WriteOutcome undo(Action original) {
        String id = original.getResourceId();
        // 잠금을 먼저 잡은 뒤 사용 여부를 봐야 진행 중인 대리 결재와 겹치지 않습니다.
        return delegations.undoCreate(id, original.getActorId(), () -> !docs.findActedUnderDelegation(id).isEmpty());
    }
}
