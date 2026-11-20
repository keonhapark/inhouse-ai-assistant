package io.inhouse.erp.write;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.OperationId;
import jakarta.servlet.http.HttpServletRequest;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ActionController {

    public record ActionView(String id, String operation, String actorId, boolean viaDelegationToken, String agentId,
                             String conversationId, String resourceType, String resourceId, String status,
                             boolean undoable, String undoActionId, OffsetDateTime createdAt) {

        static ActionView of(Action a) {
            return new ActionView(a.getId(), a.getOperation(), a.getActorId(), a.isViaDelegationToken(),
                    a.getAgentId(), a.getConversationId(), a.getResourceType(), a.getResourceId(), a.getStatus(),
                    a.isUndoable(), a.getUndoActionId(), a.getCreatedAt());
        }
    }

    private final ActionRepository actions;
    private final WriteExecutor writes;
    private final Map<String, UndoHandler> undoHandlers;

    public ActionController(ActionRepository actions, WriteExecutor writes, List<UndoHandler> handlers) {
        this.actions = actions;
        this.writes = writes;
        this.undoHandlers = handlers.stream().collect(Collectors.toMap(UndoHandler::operation, Function.identity()));
    }

    @GetMapping("/actions/{actionId}")
    @OperationId("getAction")
    @RequiredScope("action:read")
    public ActionView get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String actionId) {
        return ActionView.of(own(p, actionId));
    }

    /** 행동을 한 사람(위임 토큰이면 토큰 주인)만 되돌립니다. 남의 행동은 있는지도 알려 주지 않고 404입니다. */
    @PostMapping("/actions/{actionId}/undo")
    @OperationId("undoAction")
    @RequiredScope("action:undo")
    public ResponseEntity<Object> undo(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String actionId,
                                       @RequestParam(defaultValue = "false") boolean dryRun,
                                       @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                       @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        Action seen = own(p, actionId);
        WriteRequest req = WriteRequest.of(p, "undoAction", seen.getResourceType(), http.getRequestURI(), body,
                dryRun, key).asUndoOf(actionId);
        return writes.run(req, () -> {
            Action a = actions.lockById(actionId).orElseThrow();
            if (a.isUndone()) {
                throw new ApiException(409, "already-undone", "이미 되돌린 행동입니다");
            }
            UndoHandler handler = undoHandlers.get(a.getOperation());
            if (!a.isUndoable() || handler == null) {
                throw new ApiException(409, "not-undoable", a.getOperation() + "은 되돌릴 수 없습니다");
            }
            WriteOutcome out = handler.undo(a);
            return new WriteOutcome(out.summary(), out.changes(), false, out.resource(), a.getResourceId(),
                    out.onBehalfOf(), out.delegationId());
        });
    }

    private Action own(ErpPrincipal p, String actionId) {
        return actions.findById(actionId)
                .filter(a -> a.getActorId().equals(p.employeeId()))
                .orElseThrow(() -> ApiException.notFound("행동이 없습니다"));
    }
}
