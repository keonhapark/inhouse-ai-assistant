package io.inhouse.erp.notification;

import io.inhouse.erp.common.Ids;
import java.time.Clock;
import java.time.OffsetDateTime;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/** 결재 차례·결과·대결 처리(후열)·대결 등록 알림. 쓰기와 같은 트랜잭션에 남깁니다(미리보기면 남지 않음). */
@Service
public class Notifications {

    public static final String APPROVAL_TURN = "approval_turn";
    public static final String APPROVAL_RESULT = "approval_result";
    public static final String DELEGATED_DECISION = "delegated_decision";
    public static final String DELEGATION_REGISTERED = "delegation_registered";

    private final NotificationRepository repo;
    private final Clock clock;

    public Notifications(NotificationRepository repo, Clock clock) {
        this.repo = repo;
        this.clock = clock;
    }

    @Transactional(propagation = Propagation.MANDATORY)
    public void send(String to, String kind, String message, String documentId, String delegationId) {
        repo.save(new Notification(Ids.next("ntf"), to, kind, message, documentId, delegationId,
                OffsetDateTime.now(clock)));
    }
}
