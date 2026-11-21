package io.inhouse.erp.sales;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface QuoteRepository extends JpaRepository<Quote, String> {

    @Query("""
            select q from Quote q
            where (:author is null or q.createdBy = :author)
              and (:status is null or q.status = :status)
            order by q.createdAt desc, q.id desc""")
    List<Quote> search(@Param("author") String author, @Param("status") String status, Limit limit);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select q from Quote q where q.id = :id")
    Optional<Quote> lockById(@Param("id") String id);
}
