package io.inhouse.erp.leave;

import org.springframework.data.jpa.repository.JpaRepository;

public interface LeaveBalanceRepository extends JpaRepository<LeaveBalance, LeaveBalance.Key> {}
