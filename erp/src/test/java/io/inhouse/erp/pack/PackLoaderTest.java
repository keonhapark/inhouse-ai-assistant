package io.inhouse.erp.pack;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;

class PackLoaderTest {

    private final Pack pack = PackLoader.load(Path.of("../packs/manufacturing"));

    @Test
    void readsOrgFormsAndFixtures() {
        assertThat(pack.id()).isEqualTo("manufacturing");
        assertThat(pack.timezone().getId()).isEqualTo("Asia/Seoul");
        assertThat(pack.units()).extracting(Pack.UnitDef::id).contains("hr", "rnd-center");
        assertThat(pack.employees()).hasSizeGreaterThanOrEqualTo(50);
        assertThat(pack.forms()).extracting(Pack.FormDef::id).containsExactly("leave", "expense", "purchase");
        assertThat(pack.forms()).extracting(Pack.FormDef::stage).containsExactly(1, 2, 2);
        assertThat(pack.maxFormStage()).isEqualTo(2);
        assertThat(pack.withFormsUpTo(1).forms()).extracting(Pack.FormDef::id).containsExactly("leave");
        assertThat(pack.rooms()).isNotEmpty();
        assertThat(pack.balances()).isNotEmpty();
        assertThat(pack.delegationPolicy().maxPeriodDays()).isEqualTo(30);
    }

    @Test
    void approvalLineRulesFollowAmount() {
        Pack.FormDef expense = pack.forms().stream().filter(f -> f.id().equals("expense")).findFirst().orElseThrow();
        assertThat(expense.amountField()).isEqualTo("amount");
        Pack.LineRule small = expense.approvalLine().get(0);
        Pack.LineRule large = expense.approvalLine().get(1);
        assertThat(small.matches(1_000_000L)).isTrue();
        assertThat(small.matches(1_000_001L)).isFalse();
        assertThat(large.matches(1_000_001L)).isTrue();
        assertThat(large.steps()).containsExactly("team_leader", "division_head");

        Pack.FormDef leave = pack.forms().get(0);
        assertThat(leave.approvalLine().get(0).matches(null)).isTrue();
        assertThat(leave.effects()).containsEntry("on_final_approval", "deduct_leave_balance");
    }

    @Test
    void grantMatchesUnitGradeOrRole() {
        Grant g = new Grant(false, java.util.Set.of("hr"), java.util.Set.of("ceo"), java.util.Set.of("hr_staff"));
        assertThat(g.matches("hr", "staff", List.of())).isTrue();
        assertThat(g.matches("sales", "ceo", List.of())).isTrue();
        assertThat(g.matches("sales", "staff", List.of("hr_staff"))).isTrue();
        assertThat(g.matches("sales", "staff", List.of("employee"))).isFalse();
        assertThat(Grant.ALL.matches("x", "y", List.of())).isTrue();
    }

    @Test
    void headGradesAreAboveLowestRank() {
        assertThat(pack.isHeadGrade("staff")).isFalse();
        assertThat(pack.isHeadGrade("team_leader")).isTrue();
        assertThat(pack.isHeadGrade("ceo")).isTrue();
    }
}
