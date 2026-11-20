package io.inhouse.erp.form;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ApprovalFormRepository extends JpaRepository<ApprovalForm, String> {
    List<ApprovalForm> findAllByOrderBySortOrder();
}
