package io.inhouse.erp.org;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.not;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.authentication;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import io.inhouse.erp.PostgresTestBase;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.leave.LeaveBalance;
import io.inhouse.erp.leave.LeaveBalanceRepository;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.pack.PackSeeder;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.security.authentication.TestingAuthenticationToken;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.RequestPostProcessor;
import org.springframework.transaction.support.TransactionTemplate;

@AutoConfigureMockMvc
class OrgApiTest extends PostgresTestBase {

    @Autowired MockMvc mvc;
    @Autowired Pack pack;
    @Autowired PackSeeder seeder;
    @Autowired EmployeeRepository employees;
    @Autowired LeaveBalanceRepository balances;
    @Autowired TransactionTemplate tx;

    static RequestPostProcessor as(String employeeId) {
        return authentication(new TestingAuthenticationToken(ErpPrincipal.employee(employeeId), null, List.of()));
    }

    private String first(String unit, String grade) {
        return pack.employees().stream().filter(e -> e.unitId().equals(unit) && e.grade().equals(grade))
                .findFirst().orElseThrow().id();
    }

    @Test
    void healthIsPublic() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("ok"));
    }

    @Test
    void unauthenticatedIsProblem401() throws Exception {
        mvc.perform(get("/me"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith("application/problem+json"))
                .andExpect(jsonPath("$.type").value("urn:problem:unauthorized"))
                .andExpect(jsonPath("$.status").value(401));
    }

    @Test
    void meHasRolesFromPackGrants() throws Exception {
        String hr = first("hr", "staff");
        mvc.perform(get("/me").with(as(hr)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(hr))
                .andExpect(jsonPath("$.unitName").value("인사팀"))
                .andExpect(jsonPath("$.roles").value(org.hamcrest.Matchers.contains("employee", "hr_staff")))
                .andExpect(jsonPath("$.hiredOn").isString());
    }

    @Test
    void accessTagsFollowRolesAndUnits() throws Exception {
        mvc.perform(get("/me/access-tags").with(as(first("hr", "staff"))))
                .andExpect(jsonPath("$.tags").value(hasItem("hr-restricted")))
                .andExpect(jsonPath("$.tags").value(not(hasItem("rnd-confidential"))));
        mvc.perform(get("/me/access-tags").with(as(first("rnd", "staff"))))
                .andExpect(jsonPath("$.tags").value(hasItem("rnd-confidential")))
                .andExpect(jsonPath("$.tags").value(not(hasItem("hr-restricted"))));
        mvc.perform(get("/me/access-tags").with(as(first("sales", "staff"))))
                .andExpect(jsonPath("$.tags").value(org.hamcrest.Matchers.contains("public", "hr-policy",
                        "finance-policy")));
    }

    @Test
    void otherEmployeeIsSummaryUnlessHr() throws Exception {
        String target = first("sales", "staff");
        mvc.perform(get("/employees/" + target).with(as(first("quality", "staff"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").isString())
                .andExpect(jsonPath("$.email").doesNotExist());
        mvc.perform(get("/employees/" + target).with(as(first("hr", "staff"))))
                .andExpect(jsonPath("$.email").isString());
        mvc.perform(get("/employees/E9999").with(as(target)))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.type").value("urn:problem:not-found"));
    }

    @Test
    void searchByNameAndUnitWithLimit() throws Exception {
        String name = pack.employees().get(10).name();
        mvc.perform(get("/employees").param("q", name.substring(1)).with(as("E0001")))
                .andExpect(jsonPath("$.items[*].name").value(hasItem(name)));
        mvc.perform(get("/employees").param("unitId", "hr").param("limit", "2").with(as("E0001")))
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[0].unitId").value("hr"));
    }

    @Test
    void unitsHaveParentAndHead() throws Exception {
        mvc.perform(get("/org/units").with(as("E0001")))
                .andExpect(jsonPath("$.items.length()").value(pack.units().size()))
                .andExpect(jsonPath("$.items[0].parentId").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.items[?(@.id=='hr')].parentId").value(hasItem("mgmt")))
                .andExpect(jsonPath("$.items[?(@.id=='hr')].headId").value(hasItem(first("hr", "team_leader"))));
    }

    @Test
    void formsComeFromPack() throws Exception {
        mvc.perform(get("/approval-forms").with(as("E0001")))
                .andExpect(jsonPath("$.items[*].id").value(org.hamcrest.Matchers.contains("leave", "expense",
                        "purchase")))
                .andExpect(jsonPath("$.items[1].amountField").value("amount"))
                .andExpect(jsonPath("$.items[0].amountField").value(org.hamcrest.Matchers.nullValue()))
                .andExpect(jsonPath("$.items[0].fieldsSchema.required").isArray());
    }

    @Test
    void reseedingKeepsChangedLeaveBalance() throws Exception {
        Pack.BalanceDef b = pack.balances().get(0);
        LeaveBalance.Key key = new LeaveBalance.Key(b.employeeId(), b.year());
        tx.executeWithoutResult(s -> balances.findById(key).orElseThrow().addPending(new BigDecimal("1.0")));
        long before = employees.count();
        seeder.run(null);
        assertThat(employees.count()).isEqualTo(before).isEqualTo(pack.employees().size());
        assertThat(balances.findById(key).orElseThrow().getAnnualPending()).isEqualByComparingTo("1.0");
        tx.executeWithoutResult(s -> balances.findById(key).orElseThrow().addPending(new BigDecimal("-1.0")));
    }
}
