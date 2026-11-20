package io.inhouse.erp.notification;

import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.org.OrgViews.Items;
import java.time.OffsetDateTime;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class NotificationController {

    public record NotificationView(String id, String kind, String message, String documentId, String delegationId,
                                   OffsetDateTime createdAt, boolean read) {}

    private final NotificationRepository repo;

    public NotificationController(NotificationRepository repo) {
        this.repo = repo;
    }

    @GetMapping("/notifications")
    @RequiredScope("notification:read")
    @Transactional(readOnly = true)
    public Items<NotificationView> list(@AuthenticationPrincipal ErpPrincipal p,
                                        @RequestParam(defaultValue = "false") boolean unreadOnly) {
        var rows = unreadOnly ? repo.findByRecipientIdAndReadFalseOrderByCreatedAtDescIdDesc(p.employeeId())
                : repo.findByRecipientIdOrderByCreatedAtDescIdDesc(p.employeeId());
        return new Items<>(rows.stream().map(n -> new NotificationView(n.getId(), n.getKind(), n.getMessage(),
                n.getDocumentId(), n.getDelegationId(), n.getCreatedAt(), n.isRead())).toList());
    }
}
