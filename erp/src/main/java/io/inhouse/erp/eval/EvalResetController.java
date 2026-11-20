package io.inhouse.erp.eval;

import io.inhouse.erp.auth.PublicEndpoint;
import io.inhouse.erp.pack.PackSeeder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 평가 전용 초기화. ERP_EVAL_RESET=1로 띄웠을 때만 빈이 생기고, 아니면 경로가 없어 404입니다.
 * 결재 문서·대결·예약·알림·행동·멱등 키·감사를 비우고 연차 잔여를 팩 고정 데이터로 다시 넣습니다.
 */
@RestController
@ConditionalOnProperty(name = "erp.eval-reset", havingValue = "1")
public class EvalResetController {

    private static final Logger log = LoggerFactory.getLogger(EvalResetController.class);

    private final JdbcTemplate jdbc;
    private final PackSeeder seeder;

    public EvalResetController(JdbcTemplate jdbc, PackSeeder seeder) {
        this.jdbc = jdbc;
        this.seeder = seeder;
        log.warn("평가 초기화 경로(POST /_eval/reset)가 켜져 있습니다. 평가 환경에서만 씁니다");
    }

    @PostMapping("/_eval/reset")
    @PublicEndpoint
    @Transactional
    public ResponseEntity<Void> reset() {
        jdbc.execute("truncate approval_step, approval_document, delegation, room_reservation, notification, "
                + "action, idempotency_record, audit_event, leave_balance restart identity");
        seeder.run(null);
        return ResponseEntity.noContent().build();
    }
}
