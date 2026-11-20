package io.inhouse.erp.approval;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ApprovalDocumentRepository extends JpaRepository<ApprovalDocument, String> {

    List<ApprovalDocument> findByRequesterIdOrderByCreatedAtDesc(String requesterId);

    @Query("""
            select distinct d from ApprovalDocument d join d.steps s
            where s.approverId = :emp or s.actedBy = :emp
            order by d.createdAt desc""")
    List<ApprovalDocument> findInvolvingApprover(@Param("emp") String employeeId);

    @Query("""
            select distinct d from ApprovalDocument d join d.steps s
            where s.delegationId = :delegationId
            order by d.createdAt desc""")
    List<ApprovalDocument> findActedUnderDelegation(@Param("delegationId") String delegationId);

    @Query("""
            select d from ApprovalDocument d
            where d.status = 'in_progress'
            order by d.createdAt desc""")
    List<ApprovalDocument> findInProgress();
}
