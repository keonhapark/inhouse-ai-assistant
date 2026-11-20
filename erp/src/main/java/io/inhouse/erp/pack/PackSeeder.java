package io.inhouse.erp.pack;

import io.inhouse.erp.form.ApprovalForm;
import io.inhouse.erp.form.ApprovalFormRepository;
import io.inhouse.erp.leave.LeaveBalance;
import io.inhouse.erp.leave.LeaveBalanceRepository;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.EmployeeRepository;
import io.inhouse.erp.org.OrgPolicy;
import io.inhouse.erp.org.OrgUnit;
import io.inhouse.erp.org.OrgUnitRepository;
import io.inhouse.erp.room.Room;
import io.inhouse.erp.room.RoomRepository;
import io.inhouse.erp.ticket.TicketFixtures;
import java.math.BigDecimal;
import java.util.HashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 시작할 때 팩을 DB에 적재합니다. 조직·직원·양식·회의실은 팩이 기준이라 매번 덮어쓰고,
 * 연차 잔여와 IT 티켓은 쓰면서 바뀌는 값이라 없을 때만 넣습니다.
 */
@Component
public class PackSeeder implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(PackSeeder.class);

    private final Pack pack;
    private final OrgPolicy policy;
    private final OrgUnitRepository units;
    private final EmployeeRepository employees;
    private final ApprovalFormRepository forms;
    private final RoomRepository rooms;
    private final LeaveBalanceRepository balances;
    private final TicketFixtures tickets;

    public PackSeeder(Pack pack, OrgPolicy policy, OrgUnitRepository units, EmployeeRepository employees,
                      ApprovalFormRepository forms, RoomRepository rooms, LeaveBalanceRepository balances,
                      TicketFixtures tickets) {
        this.pack = pack;
        this.policy = policy;
        this.units = units;
        this.employees = employees;
        this.forms = forms;
        this.rooms = rooms;
        this.balances = balances;
        this.tickets = tickets;
    }

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        Map<String, String> heads = new HashMap<>();
        for (Pack.EmployeeDef e : pack.employees()) {
            if (pack.isHeadGrade(e.grade())) {
                heads.put(e.unitId(), e.id());
            }
        }
        int i = 0;
        for (Pack.UnitDef u : pack.units()) {
            OrgUnit unit = units.findById(u.id()).orElseGet(() -> new OrgUnit(u.id(), u.name(), u.kind(), null, null, 0));
            unit.update(u.name(), u.kind(), u.parent(), heads.get(u.id()), i++);
            units.saveAndFlush(unit);
        }
        for (Pack.EmployeeDef e : pack.employees()) {
            Employee emp = employees.findById(e.id()).orElseGet(() -> new Employee(e.id()));
            emp.update(e.employeeNo(), e.name(), e.unitId(), e.grade(), e.email(), e.hiredOn(),
                    policy.rolesOf(e.unitId(), e.grade()));
            employees.save(emp);
        }
        i = 0;
        for (Pack.FormDef f : pack.forms()) {
            ApprovalForm form = forms.findById(f.id()).orElseGet(() -> new ApprovalForm(f.id()));
            form.update(f.name(), f.fields(), f.amountField(), i++);
            forms.save(form);
        }
        for (Pack.RoomDef r : pack.rooms()) {
            Room room = rooms.findById(r.id()).orElseGet(() -> new Room(r.id()));
            room.update(r.name(), r.floor(), r.capacity());
            rooms.save(room);
        }
        employees.flush();
        int added = 0;
        for (Pack.BalanceDef b : pack.balances()) {
            if (!balances.existsById(new LeaveBalance.Key(b.employeeId(), b.year()))) {
                balances.save(new LeaveBalance(b.employeeId(), b.year(), BigDecimal.valueOf(b.annualTotal()),
                        BigDecimal.valueOf(b.annualUsed())));
                added++;
            }
        }
        int newTickets = tickets.seed(pack.tickets());
        log.info("팩 {} 적재: 조직 {}, 직원 {}, 양식 {}, 회의실 {}, 새 연차 잔여 {}, 새 티켓 {}", pack.id(),
                pack.units().size(), pack.employees().size(), pack.forms().size(), pack.rooms().size(), added,
                newTickets);
    }
}
