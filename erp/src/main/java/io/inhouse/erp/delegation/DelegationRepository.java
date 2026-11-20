package io.inhouse.erp.delegation;

import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface DelegationRepository extends JpaRepository<Delegation, String> {

    List<Delegation> findByDelegatorIdOrderByCreatedAtDesc(String delegatorId);

    List<Delegation> findByDelegateIdOrderByCreatedAtDesc(String delegateId);

    List<Delegation> findAllByOrderByCreatedAtDesc();

    List<Delegation> findByDelegatorIdAndDelegateId(String delegatorId, String delegateId);

    List<Delegation> findByDelegatorIdInAndDelegateId(Collection<String> delegatorIds, String delegateId);

    /** 해지·등록 되돌리기: 이 위임으로 진행 중인 대리 결재와 줄을 세웁니다. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select d from Delegation d where d.id = :id")
    Optional<Delegation> lockById(@Param("id") String id);

    /** 대리 결재: 결재가 커밋될 때까지 위임이 해지되지 않게 공유 잠금을 겁니다. */
    @Lock(LockModeType.PESSIMISTIC_READ)
    @Query("select d from Delegation d where d.id = :id")
    Optional<Delegation> shareLockById(@Param("id") String id);
}
