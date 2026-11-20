package io.inhouse.erp.org;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface OrgUnitRepository extends JpaRepository<OrgUnit, String> {
    List<OrgUnit> findAllByOrderBySortOrder();
}
