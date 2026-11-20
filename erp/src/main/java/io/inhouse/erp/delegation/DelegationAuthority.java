package io.inhouse.erp.delegation;

import io.inhouse.erp.approval.ApprovalDocument;
import io.inhouse.erp.approval.ApprovalDocumentRepository;
import io.inhouse.erp.approval.ApprovalStep;
import io.inhouse.erp.approval.DelegateAuthority;
import io.inhouse.erp.common.ApiException;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.stereotype.Component;

/**
 * 대리 결재 판단(기획서 5-4). 대리인이 결재하는 시점에 원 결재자가 등록한 위임이 유효한지(기간·해지),
 * 결재 건이 위임 범위(양식·금액) 안인지 봅니다. 위임의 위임(재위임)은 따라가지 않습니다.
 * 요청자 본인 결재 금지는 결재 엔진이 먼저 확인합니다.
 */
@Component
public class DelegationAuthority implements DelegateAuthority {

    /** 같은 결재자·대리인 사이에 위임이 여럿이고 모두 안 될 때 알려 줄 이유의 우선순위. */
    private static final List<String> PRIORITY = List.of("delegation-out-of-scope", "delegation-out-of-period",
            "delegation-revoked");

    private final DelegationRepository delegations;
    private final ApprovalDocumentRepository docs;
    private final Clock clock;

    public DelegationAuthority(DelegationRepository delegations, ApprovalDocumentRepository docs, Clock clock) {
        this.delegations = delegations;
        this.docs = docs;
        this.clock = clock;
    }

    @Override
    public String authorize(ApprovalDocument doc, String approverId, String actorId) {
        OffsetDateTime now = OffsetDateTime.now(clock);
        List<Delegation> direct = delegations.findByDelegatorIdAndDelegateId(approverId, actorId);
        if (direct.isEmpty()) {
            Set<String> middle = delegations.findByDelegatorIdOrderByCreatedAtDesc(approverId).stream()
                    .map(Delegation::getDelegateId).collect(Collectors.toSet());
            if (!middle.isEmpty() && !delegations.findByDelegatorIdInAndDelegateId(middle, actorId).isEmpty()) {
                throw new ApiException(403, "redelegation-not-allowed", "재위임은 따라가지 않습니다");
            }
            if (doc.getSteps().stream().anyMatch(s -> s.getApproverId().equals(actorId))) {
                throw new ApiException(403, "not-current-approver", "현재 결재 차례가 아닙니다");
            }
            throw ApiException.notFound("결재 문서가 없습니다");
        }
        List<String> problems = new ArrayList<>();
        for (Delegation d : direct) {
            // 해지와 겹치지 않게 공유 잠금을 건 뒤 다시 봅니다.
            Delegation locked = delegations.shareLockById(d.getId()).orElseThrow();
            String problem = locked.problemFor(doc.getFormId(), doc.getAmount(), now);
            if (problem == null) {
                return locked.getId();
            }
            problems.add(problem);
        }
        for (String code : PRIORITY) {
            if (problems.contains(code)) {
                throw new ApiException(403, code);
            }
        }
        throw new ApiException(403, "delegation-not-found");
    }

    @Override
    public boolean canView(ApprovalDocument doc, String employeeId) {
        OffsetDateTime now = OffsetDateTime.now(clock);
        Set<String> approvers = doc.getSteps().stream().map(ApprovalStep::getApproverId).collect(Collectors.toSet());
        return delegations.findByDelegatorIdInAndDelegateId(approvers, employeeId).stream()
                .anyMatch(d -> d.problemFor(doc.getFormId(), doc.getAmount(), now) == null);
    }

    @Override
    public List<ApprovalDocument> delegatedInbox(String employeeId) {
        OffsetDateTime now = OffsetDateTime.now(clock);
        List<Delegation> mine = delegations.findByDelegateIdOrderByCreatedAtDesc(employeeId).stream()
                .filter(d -> "active".equals(d.status(now))).toList();
        if (mine.isEmpty()) {
            return List.of();
        }
        Set<String> delegators = mine.stream().map(Delegation::getDelegatorId).collect(Collectors.toSet());
        return docs.findInProgressAwaiting(delegators).stream()
                .filter(doc -> !doc.getRequesterId().equals(employeeId))
                .filter(doc -> mine.stream().anyMatch(d -> d.getDelegatorId().equals(doc.current().getApproverId())
                        && d.problemFor(doc.getFormId(), doc.getAmount(), now) == null))
                .toList();
    }
}
