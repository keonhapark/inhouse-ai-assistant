package io.inhouse.erp.approval;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.approval.ApprovalViews.DocumentView;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.common.Ko;
import io.inhouse.erp.leave.LeaveService;
import io.inhouse.erp.notification.Notifications;
import io.inhouse.erp.org.Employee;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 결재 문서 엔진: 상신, 승인, 반려, 회수와 결재함. 쓰기 메서드는 WriteExecutor의 트랜잭션 안에서 불립니다.
 * 양식과 결재선, 휴가 차감 같은 효과는 팩(forms.yaml)에서 읽습니다.
 */
@Service
public class ApprovalService {

    static final String DEDUCT_LEAVE = "deduct_leave_balance";

    private final Map<String, Pack.FormDef> forms;
    private final ApprovalDocumentRepository docs;
    private final ApprovalLineResolver lines;
    private final FormValidator validator;
    private final DelegateAuthority delegates;
    private final LeaveService leave;
    private final Notifications notifications;
    private final OrgService org;
    private final ObjectMapper mapper;
    private final Clock clock;

    public ApprovalService(Pack pack, ApprovalDocumentRepository docs, ApprovalLineResolver lines,
                           FormValidator validator, DelegateAuthority delegates, LeaveService leave,
                           Notifications notifications, OrgService org, ObjectMapper mapper, Clock clock) {
        this.forms = pack.forms().stream().collect(Collectors.toMap(Pack.FormDef::id, Function.identity()));
        this.docs = docs;
        this.lines = lines;
        this.validator = validator;
        this.delegates = delegates;
        this.leave = leave;
        this.notifications = notifications;
        this.org = org;
        this.mapper = mapper;
        this.clock = clock;
    }

    // ---------- 상신 ----------

    public WriteOutcome create(ErpPrincipal p, String formId, String title, JsonNode fields) {
        Pack.FormDef form = forms.get(formId);
        if (form == null) {
            throw ApiException.validation("formId", "unknown");
        }
        validator.validate(form, fields);
        Employee requester = org.employee(p.employeeId());
        Long amount = form.amountField() != null && fields.hasNonNull(form.amountField())
                ? fields.get(form.amountField()).asLong() : null;
        BigDecimal days = deductsLeave(form)
                ? LeaveService.days(fields.path("leave_type").asText(), fields.path("start_date").asText(null),
                fields.path("end_date").asText(null))
                : BigDecimal.ZERO;
        List<String> line = lines.resolve(form, requester, amount);
        leave.reserve(requester.getId(), days, line.isEmpty());

        OffsetDateTime now = OffsetDateTime.now(clock);
        String docTitle = title == null || title.isBlank() ? form.name() + " - " + requester.getName() : title;
        ApprovalDocument d = docs.saveAndFlush(new ApprovalDocument(Ids.next("doc"), form.id(), docTitle,
                requester.getId(), fields.deepCopy(), amount, days, line, now));
        if (!line.isEmpty()) {
            notifications.send(line.get(0), Notifications.APPROVAL_TURN, "결재 대기: " + docTitle, d.getId(), null);
        }
        DocumentView view = view(d);
        return WriteOutcome.of(form.name() + " 결재를 올립니다(결재선 " + line.size() + "단계)",
                new Change("create", "approval_document", d.getId(), null, json(view)), true, view, d.getId());
    }

    /** 상신 되돌리기: 아직 아무도 결재하지 않았으면 회수와 같습니다. */
    public WriteOutcome undoCreate(String documentId) {
        ApprovalDocument d = docs.findById(documentId).orElseThrow();
        if (!ApprovalDocument.IN_PROGRESS.equals(d.getStatus()) || !d.nobodyActed()) {
            throw new ApiException(409, "undo-conflict", "이미 결재가 시작돼 실행 취소할 수 없습니다. 기안함에서 문서 상태를 확인하세요.");
        }
        JsonNode before = json(view(d));
        close(d, ApprovalDocument.WITHDRAWN);
        DocumentView after = flushAndView(d);
        return WriteOutcome.of("상신을 취소하고 문서를 회수했습니다",
                new Change("update", "approval_document", d.getId(), before, json(after)), false, after, d.getId());
    }

    // ---------- 승인·반려 ----------

    /**
     * 현재 단계 결재자 본인이나 그 결재자의 유효한 대리인이 결재합니다. 요청자 본인은 어떤 경로로도 결재하지 못합니다.
     * 화면이 본 version과 지금 version이 다르면 409입니다.
     */
    public WriteOutcome decide(ErpPrincipal p, String documentId, int version, String comment, boolean approve) {
        ApprovalDocument d = docs.findById(documentId).orElseThrow(() -> ApiException.notFound("결재 문서가 없습니다"));
        if (!ApprovalDocument.IN_PROGRESS.equals(d.getStatus())) {
            throw new ApiException(409, "invalid-state", "이미 결재가 끝난 문서입니다(" + Ko.approvalStatus(d.getStatus()) + ").");
        }
        String actor = p.employeeId();
        if (actor.equals(d.getRequesterId())) {
            throw new ApiException(403, "self-approval-forbidden");
        }
        ApprovalStep step = d.current();
        String approver = step.getApproverId();
        String delegationId = actor.equals(approver) ? null : delegates.authorize(d, approver, actor);
        if (version != d.getVersion()) {
            throw new ApiException(409, "version-conflict", "새로 고친 뒤 다시 확인하세요.");
        }
        JsonNode before = json(view(d));
        OffsetDateTime now = OffsetDateTime.now(clock);
        step.act(approve ? "approved" : "rejected", actor, delegationId == null ? null : approver, delegationId, now,
                comment);
        String actorName = org.employee(actor).getName();
        if (delegationId != null) {
            notifications.send(approver, Notifications.DELEGATED_DECISION, "후열(대결 내역 확인): " + actorName
                    + "님이 대결로 '" + d.getTitle() + "' 문서를 " + (approve ? "승인" : "반려") + "했습니다", d.getId(), delegationId);
        }
        if (!approve) {
            close(d, ApprovalDocument.REJECTED);
            notifications.send(d.getRequesterId(), Notifications.APPROVAL_RESULT, "반려: " + d.getTitle(), d.getId(),
                    null);
        } else if (d.isLastStep()) {
            close(d, ApprovalDocument.APPROVED);
            notifications.send(d.getRequesterId(), Notifications.APPROVAL_RESULT, "승인 완료: " + d.getTitle(),
                    d.getId(), null);
        } else {
            d.advance(now);
            notifications.send(d.current().getApproverId(), Notifications.APPROVAL_TURN, "결재 대기: " + d.getTitle(),
                    d.getId(), null);
        }
        DocumentView after = flushAndView(d);
        String who = delegationId == null ? "" : "(" + org.employee(approver).getName() + "님 대결)";
        WriteOutcome out = WriteOutcome.of("'" + d.getTitle() + "' 문서를 " + (approve ? "승인" : "반려") + "합니다" + who,
                new Change("update", "approval_document", d.getId(), before, json(after)), false, after, d.getId());
        return delegationId == null ? out : out.withDelegation(approver, delegationId);
    }

    // ---------- 회수 ----------

    /** 요청자 본인만 합니다. 진행 중이면 회수하고, 최종 승인된 휴가는 시작일 전이면 회수하며 잔여를 돌려놓습니다. */
    public WriteOutcome withdraw(ErpPrincipal p, String documentId) {
        ApprovalDocument d = visible(p.employeeId(), documentId);
        if (!d.getRequesterId().equals(p.employeeId())) {
            throw ApiException.forbidden("기안자만 회수할 수 있습니다.");
        }
        JsonNode before = json(view(d));
        boolean futureApprovedLeave = ApprovalDocument.APPROVED.equals(d.getStatus()) && d.getLeaveDays().signum() > 0
                && LeaveService.date("start_date", d.getFields().path("start_date").asText(null))
                .isAfter(LocalDate.now(clock));
        if (ApprovalDocument.IN_PROGRESS.equals(d.getStatus()) || futureApprovedLeave) {
            close(d, ApprovalDocument.WITHDRAWN);
        } else {
            throw new ApiException(409, "invalid-state", Ko.approvalStatus(d.getStatus()) + "된 문서라 회수할 수 없습니다.");
        }
        DocumentView after = flushAndView(d);
        return WriteOutcome.of("'" + d.getTitle() + "' 문서를 회수합니다",
                new Change("update", "approval_document", d.getId(), before, json(after)), false, after, d.getId());
    }

    /** 응답 형태(계약 ApprovalDocument). fields는 양식 정의 순서입니다. */
    public DocumentView view(ApprovalDocument d) {
        return ApprovalViews.of(d, forms.get(d.getFormId()));
    }

    /** 문서를 끝내고 휴가 잔여를 맞춥니다. */
    private void close(ApprovalDocument d, String status) {
        String was = d.getStatus();
        BigDecimal days = d.getLeaveDays();
        d.close(status, OffsetDateTime.now(clock));
        if (days.signum() == 0) {
            return;
        }
        if (ApprovalDocument.IN_PROGRESS.equals(was) && ApprovalDocument.APPROVED.equals(status)) {
            leave.commit(d.getRequesterId(), days);
        } else if (ApprovalDocument.IN_PROGRESS.equals(was)) {
            leave.release(d.getRequesterId(), days);
        } else if (ApprovalDocument.APPROVED.equals(was) && ApprovalDocument.WITHDRAWN.equals(status)) {
            leave.restore(d.getRequesterId(), days);
        }
    }

    // ---------- 조회 ----------

    /** 요청자, 결재선에 있는 사람, 결재한 사람, 결재자의 유효한 대리인만 봅니다. 그 밖에는 404입니다. */
    @Transactional(readOnly = true)
    public ApprovalDocument visible(String employeeId, String documentId) {
        ApprovalDocument d = docs.findById(documentId).orElseThrow(() -> ApiException.notFound("결재 문서가 없습니다"));
        if (d.involves(employeeId) || delegates.canView(d, employeeId)) {
            return d;
        }
        throw ApiException.notFound("결재 문서가 없습니다");
    }

    @Transactional(readOnly = true)
    public List<DocumentView> list(String employeeId, String box, String status, int limit) {
        Limit max = Limit.of(Math.max(1, Math.min(limit, 100)));
        List<ApprovalDocument> found = switch (box) {
            case "outbox" -> docs.outbox(employeeId, status, max);
            case "inbox" -> docs.inbox(employeeId, status, max);
            case "done" -> docs.done(employeeId, status, max);
            case "delegated" -> delegates.delegatedInbox(employeeId).stream()
                    .filter(d -> status == null || status.equals(d.getStatus()))
                    .sorted(Comparator.comparing(ApprovalDocument::getCreatedAt).reversed())
                    .limit(max.max()).toList();
            default -> throw ApiException.validation("box", "outbox, inbox, delegated, done 중 하나");
        };
        return found.stream().map(this::view).toList();
    }

    private static boolean deductsLeave(Pack.FormDef form) {
        return DEDUCT_LEAVE.equals(form.effects().get("on_final_approval"));
    }

    private DocumentView flushAndView(ApprovalDocument d) {
        return view(docs.saveAndFlush(d));
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }
}
