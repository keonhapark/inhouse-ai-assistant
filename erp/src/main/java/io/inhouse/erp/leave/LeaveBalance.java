package io.inhouse.erp.leave;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.IdClass;
import jakarta.persistence.Table;
import java.io.Serializable;
import java.math.BigDecimal;

/** 연차 잔여. remaining = total - used - pending. 반차는 0.5일입니다. */
@Entity
@Table(name = "leave_balance")
@IdClass(LeaveBalance.Key.class)
public class LeaveBalance {

    public record Key(String employeeId, int year) implements Serializable {
        public Key() {
            this(null, 0);
        }
    }

    @Id
    @Column(name = "employee_id")
    private String employeeId;
    @Id
    private int year;
    @Column(name = "annual_total")
    private BigDecimal annualTotal;
    @Column(name = "annual_used")
    private BigDecimal annualUsed;
    @Column(name = "annual_pending")
    private BigDecimal annualPending;

    protected LeaveBalance() {}

    public LeaveBalance(String employeeId, int year, BigDecimal total, BigDecimal used) {
        this.employeeId = employeeId;
        this.year = year;
        this.annualTotal = total;
        this.annualUsed = used;
        this.annualPending = BigDecimal.ZERO;
    }

    public BigDecimal remaining() {
        return annualTotal.subtract(annualUsed).subtract(annualPending);
    }

    public void addPending(BigDecimal days) { annualPending = annualPending.add(days); }
    public void addUsed(BigDecimal days) { annualUsed = annualUsed.add(days); }

    public String getEmployeeId() { return employeeId; }
    public int getYear() { return year; }
    public BigDecimal getAnnualTotal() { return annualTotal; }
    public BigDecimal getAnnualUsed() { return annualUsed; }
    public BigDecimal getAnnualPending() { return annualPending; }
}
