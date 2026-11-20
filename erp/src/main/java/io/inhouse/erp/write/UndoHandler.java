package io.inhouse.erp.write;

/**
 * 되돌릴 수 있는 쓰기마다 하나씩 둡니다. 실행과 같은 트랜잭션 안에서 불리고, 되돌릴 수 없는 상태면
 * 409 undo-conflict를 던집니다(부분 되돌리기는 없습니다).
 */
public interface UndoHandler {

    /** 되돌릴 행동의 operationId(예: createApprovalDocument). */
    String operation();

    WriteOutcome undo(Action original);
}
