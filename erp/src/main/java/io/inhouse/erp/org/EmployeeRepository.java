package io.inhouse.erp.org;

import java.util.List;
import java.util.Optional;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface EmployeeRepository extends JpaRepository<Employee, String> {

    Optional<Employee> findByEmployeeNo(String employeeNo);

    @Query("""
            select e from Employee e
            where (:q is null or e.name like concat('%', cast(:q as string), '%'))
              and (:unitId is null or e.unitId = :unitId)
            order by e.id""")
    List<Employee> search(@Param("q") String q, @Param("unitId") String unitId, Limit limit);
}
