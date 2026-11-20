package io.inhouse.erp.approval;

import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ApprovalDocumentRepository extends JpaRepository<ApprovalDocument, String> {

    /** 보낸 결재함. 결재 단계는 batch fetch로 함께 읽습니다. */
    @Query("""
            select d from ApprovalDocument d
            where d.requesterId = :emp and (:status is null or d.status = :status)
            order by d.createdAt desc""")
    List<ApprovalDocument> outbox(@Param("emp") String employeeId, @Param("status") String status, Limit limit);

    /** 받은 결재함: 진행 중이고 지금 단계 결재자가 나인 문서. */
    @Query("""
            select d from ApprovalDocument d join d.steps s
            where d.status = 'in_progress' and s.stepOrder = d.currentStep and s.approverId = :emp
              and (:status is null or d.status = :status)
            order by d.createdAt desc""")
    List<ApprovalDocument> inbox(@Param("emp") String employeeId, @Param("status") String status, Limit limit);

    /** 처리한 결재함: 내가 결재한(대결 포함) 단계가 있는 문서. */
    @Query("""
            select d from ApprovalDocument d
            where exists (select 1 from ApprovalDocument x join x.steps s where x = d and s.actedBy = :emp)
              and (:status is null or d.status = :status)
            order by d.createdAt desc""")
    List<ApprovalDocument> done(@Param("emp") String employeeId, @Param("status") String status, Limit limit);

    @Query("""
            select distinct d from ApprovalDocument d join d.steps s
            where s.delegationId = :delegationId
            order by d.createdAt desc""")
    List<ApprovalDocument> findActedUnderDelegation(@Param("delegationId") String delegationId);
}
