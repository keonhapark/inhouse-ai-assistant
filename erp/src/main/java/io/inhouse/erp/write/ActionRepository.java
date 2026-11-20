package io.inhouse.erp.write;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ActionRepository extends JpaRepository<Action, String> {

    /** 되돌리기는 같은 행동을 동시에 두 번 되돌리지 않게 행을 잠급니다. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from Action a where a.id = :id")
    Optional<Action> lockById(@Param("id") String id);
}
