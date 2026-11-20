package io.inhouse.erp.org;

import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OrderColumn;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "employee")
public class Employee {

    @Id
    private String id;
    @Column(name = "employee_no")
    private String employeeNo;
    private String name;
    @Column(name = "unit_id")
    private String unitId;
    private String grade;
    private String email;
    @Column(name = "hired_on")
    private LocalDate hiredOn;

    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "employee_role", joinColumns = @JoinColumn(name = "employee_id"))
    @OrderColumn(name = "sort_order")
    @Column(name = "role_id")
    private List<String> roles = new ArrayList<>();

    protected Employee() {}

    public Employee(String id) {
        this.id = id;
    }

    public void update(String employeeNo, String name, String unitId, String grade, String email,
                       LocalDate hiredOn, List<String> roles) {
        this.employeeNo = employeeNo;
        this.name = name;
        this.unitId = unitId;
        this.grade = grade;
        this.email = email;
        this.hiredOn = hiredOn;
        this.roles.clear();
        this.roles.addAll(roles);
    }

    public boolean hasRole(String role) {
        return roles.contains(role);
    }

    public String getId() { return id; }
    public String getEmployeeNo() { return employeeNo; }
    public String getName() { return name; }
    public String getUnitId() { return unitId; }
    public String getGrade() { return grade; }
    public String getEmail() { return email; }
    public LocalDate getHiredOn() { return hiredOn; }
    public List<String> getRoles() { return List.copyOf(roles); }
}
