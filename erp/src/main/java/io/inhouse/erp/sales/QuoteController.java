package io.inhouse.erp.sales;

import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.auth.RequiredScope;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Bodies;
import io.inhouse.erp.common.OperationId;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.write.WriteExecutor;
import io.inhouse.erp.write.WriteRequest;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
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
public class QuoteController {

    private static final String RESOURCE = "quote";
    static final int MAX_LINES = 20;

    private final QuoteService quotes;
    private final WriteExecutor writes;

    public QuoteController(QuoteService quotes, WriteExecutor writes) {
        this.quotes = quotes;
        this.writes = writes;
    }

    @GetMapping("/sales/quotes")
    @OperationId("listQuotes")
    @RequiredScope("sales:read")
    public Items<QuoteService.View> list(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "mine") String box,
                                         @RequestParam(required = false) String status,
                                         @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(quotes.list(p.employeeId(), box, status, limit));
    }

    @GetMapping("/sales/quotes/{quoteId}")
    @OperationId("getQuote")
    @RequiredScope("sales:read")
    public QuoteService.View get(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String quoteId) {
        return quotes.get(p.employeeId(), quoteId);
    }

    @PostMapping("/sales/quotes")
    @OperationId("createQuote")
    @RequiredScope("sales:write")
    public ResponseEntity<Object> create(@AuthenticationPrincipal ErpPrincipal p,
                                         @RequestParam(defaultValue = "false") boolean dryRun,
                                         @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                         @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        quotes.requireFeature();
        quotes.requireSalesRep(p.employeeId());
        Bodies.check(body, Set.of("customerId", "lines", "validUntil", "note"), Set.of("customerId", "lines"));
        JsonNode raw = body.get("lines");
        if (!raw.isArray() || raw.isEmpty() || raw.size() > MAX_LINES) {
            throw ApiException.validation("lines", "1~" + MAX_LINES + "줄");
        }
        List<QuoteService.LineRequest> lines = new ArrayList<>();
        for (JsonNode l : raw) {
            String at = "lines/" + lines.size();
            try {
                Bodies.check(l, Set.of("itemCode", "quantity"), Set.of("itemCode", "quantity"));
                int qty = Bodies.integer(l, "quantity");
                if (qty < 1 || qty > 1_000_000) {
                    throw ApiException.validation("quantity", "1~1000000");
                }
                lines.add(new QuoteService.LineRequest(Bodies.text(l, "itemCode", 32), qty));
            } catch (ApiException e) {
                throw prefixed(at, e);
            }
        }
        LocalDate valid = null;
        String v = Bodies.text(body, "validUntil", 10);
        if (v != null) {
            try {
                valid = LocalDate.parse(v);
            } catch (DateTimeParseException e) {
                throw ApiException.validation("validUntil", "YYYY-MM-DD");
            }
        }
        QuoteService.CreateRequest req = new QuoteService.CreateRequest(Bodies.text(body, "customerId", 32), lines,
                valid, Bodies.text(body, "note", 500));
        WriteRequest w = WriteRequest.of(p, "createQuote", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> quotes.create(p, req));
    }

    /** 줄 안 오류의 필드 이름에 lines/{i}/를 붙입니다(줄이 객체가 아니면 lines/{i}). */
    private static ApiException prefixed(String at, ApiException e) {
        List<ApiException.FieldError> errors = e.errors().isEmpty()
                ? List.of(new ApiException.FieldError(at, "object with itemCode, quantity required"))
                : e.errors().stream().map(f -> new ApiException.FieldError(at + "/" + f.field(), f.message())).toList();
        return new ApiException(e.status(), e.code(), at + ": " + e.detail(), errors);
    }

    @PostMapping("/sales/quotes/{quoteId}/issue")
    @OperationId("issueQuote")
    @RequiredScope(value = "sales:issue", humanOnly = true)
    public ResponseEntity<Object> issue(@AuthenticationPrincipal ErpPrincipal p, @PathVariable String quoteId,
                                        @RequestParam(defaultValue = "false") boolean dryRun,
                                        @RequestHeader(value = "Idempotency-Key", required = false) String key,
                                        @RequestBody(required = false) JsonNode body, HttpServletRequest http) {
        quotes.requireFeature();
        Bodies.check(body, Set.of("version"), Set.of("version"));
        int version = Bodies.integer(body, "version");
        WriteRequest w = WriteRequest.of(p, "issueQuote", RESOURCE, http.getRequestURI(), body, dryRun, key);
        return writes.run(w, () -> quotes.issue(p, quoteId, version));
    }

    @GetMapping("/items")
    @OperationId("listItems")
    @RequiredScope("item:read")
    public Items<QuoteService.ItemView> items(@RequestParam(required = false) String q,
                                              @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(quotes.items(q, limit));
    }

    @GetMapping("/customers")
    @OperationId("listCustomers")
    @RequiredScope("customer:read")
    public Items<QuoteService.CustomerView> customers(@AuthenticationPrincipal ErpPrincipal p,
                                                      @RequestParam(required = false) String q,
                                                      @RequestParam(defaultValue = "20") int limit) {
        return new Items<>(quotes.customers(p.employeeId(), q, limit));
    }
}
