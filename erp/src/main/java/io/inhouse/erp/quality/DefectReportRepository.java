package io.inhouse.erp.quality;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface DefectReportRepository extends JpaRepository<DefectReport, String> {

    @Query("""
            select d from DefectReport d
            where (:author is null or d.createdBy = :author)
              and (:status is null or d.status = :status)
            order by d.createdAt desc, d.id desc""")
    List<DefectReport> search(@Param("author") String author, @Param("status") String status, Limit limit);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select d from DefectReport d where d.id = :id")
    Optional<DefectReport> lockById(@Param("id") String id);
}
