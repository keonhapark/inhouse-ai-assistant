package io.inhouse.erp.sales;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.common.Ko;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 견적·품목·고객사(계약 erp.yaml sales·catalog). 팩 기능 sales가 없으면 견적·고객사는 404입니다. 견적 작성·전체 조회·
 * 발행은 영업 역할(팩 erp_roles.sales_rep)만 합니다. 단가는 품목 단가를 넣고 줄 금액·합계는 erp가 계산합니다.
 */
@Service
public class QuoteService {

    static final String FEATURE = "sales";
    static final int DEFAULT_VALID_DAYS = 30;

    public record Line(String itemCode, String itemName, int quantity, long unitPrice, long amount) {}

    public record View(String id, String createdBy, String customerId, String customerName, List<Line> lines,
                       long totalAmount, LocalDate validUntil, String note, String status, int version,
                       String issuedBy, OffsetDateTime createdAt, OffsetDateTime updatedAt) {}

    public record LineRequest(String itemCode, int quantity) {}

    public record CreateRequest(String customerId, List<LineRequest> lines, LocalDate validUntil, String note) {}

    public record ItemView(String code, String name, String unit, long unitPrice, int stock) {}

    public record Contact(String name, String email, String phone) {}

    public record CustomerView(String id, String name, Contact contact) {}

    private final QuoteRepository quotes;
    private final OrgService org;
    private final Pack pack;
    private final ObjectMapper mapper;
    private final ZoneId zone;
    private final Clock clock;

    public QuoteService(QuoteRepository quotes, OrgService org, Pack pack, ObjectMapper mapper, Clock clock) {
        this.quotes = quotes;
        this.org = org;
        this.pack = pack;
        this.mapper = mapper;
        this.zone = pack.timezone();
        this.clock = clock;
    }

    public void requireFeature() {
        if (!pack.hasFeature(FEATURE)) {
            throw ApiException.notFound("없는 경로입니다");
        }
    }

    // ---------- 품목·고객사 ----------

    public List<ItemView> items(String q, int limit) {
        return pack.items().stream()
                .filter(i -> q == null || q.isBlank() || i.code().toLowerCase().contains(q.toLowerCase())
                        || i.name().contains(q))
                .limit(Math.max(1, Math.min(limit, 100)))
                .map(i -> new ItemView(i.code(), i.name(), i.unit(), i.unitPrice(), i.stock())).toList();
    }

    /** 영업 역할이 아니면 연락처를 주지 않습니다. */
    public List<CustomerView> customers(String employeeId, String q, int limit) {
        requireFeature();
        boolean rep = org.isSalesRep(employeeId);
        return pack.customers().stream().filter(c -> q == null || q.isBlank() || c.name().contains(q))
                .limit(Math.max(1, Math.min(limit, 100)))
                .map(c -> new CustomerView(c.id(), c.name(),
                        rep ? new Contact(c.contactName(), c.contactEmail(), c.contactPhone()) : null)).toList();
    }

    // ---------- 견적 ----------

    @Transactional(readOnly = true)
    public List<View> list(String employeeId, String box, String status, int limit) {
        requireFeature();
        if (!"mine".equals(box) && !"all".equals(box)) {
            throw ApiException.validation("box", "mine, all 중 하나");
        }
        if (status != null && !Quote.STATUSES.contains(status)) {
            throw ApiException.validation("status", "unknown");
        }
        if ("all".equals(box) && !org.isSalesRep(employeeId)) {
            throw ApiException.forbidden("전체 목록은 영업 담당만 볼 수 있습니다.");
        }
        return quotes.search("mine".equals(box) ? employeeId : null, status,
                Limit.of(Math.max(1, Math.min(limit, 100)))).stream().map(this::view).toList();
    }

    @Transactional(readOnly = true)
    public View get(String employeeId, String id) {
        requireFeature();
        return view(visible(employeeId, quotes.findById(id).orElse(null)));
    }

    /** 견적 작성은 영업 역할만. 본문 검사(422)보다 먼저 봅니다. */
    public void requireSalesRep(String employeeId) {
        if (!org.isSalesRep(employeeId)) {
            throw ApiException.forbidden("견적은 영업 담당만 쓸 수 있습니다.");
        }
    }

    public WriteOutcome create(ErpPrincipal p, CreateRequest req) {
        requireFeature();
        requireSalesRep(p.employeeId());
        Pack.CustomerDef customer = pack.customer(req.customerId())
                .orElseThrow(() -> ApiException.validation("customerId", "unknown"));
        List<Line> lines = new ArrayList<>();
        long total;
        try {
            for (int i = 0; i < req.lines().size(); i++) {
                LineRequest l = req.lines().get(i);
                Pack.ItemDef item = pack.item(l.itemCode())
                        .orElseThrow(() -> ApiException.validation("lines/" + lines.size() + "/itemCode", "unknown"));
                lines.add(new Line(item.code(), item.name(), l.quantity(), item.unitPrice(),
                        Math.multiplyExact(l.quantity(), item.unitPrice())));
            }
            total = lines.stream().mapToLong(Line::amount).reduce(0L, Math::addExact);
        } catch (ArithmeticException e) {
            throw ApiException.invalid("lines", "견적 금액이 너무 큽니다. 수량이나 품목을 줄이세요.");
        }
        LocalDate today = LocalDate.now(clock.withZone(zone));
        LocalDate valid = req.validUntil() == null ? today.plusDays(DEFAULT_VALID_DAYS) : req.validUntil();
        if (valid.isBefore(today)) {
            throw ApiException.invalid("validUntil", "유효 기한은 오늘 이후 날짜로 고르세요.");
        }
        Quote q = quotes.saveAndFlush(new Quote(Ids.next("quo"), p.employeeId(), customer.id(), customer.name(),
                mapper.valueToTree(lines), total, valid, req.note(), OffsetDateTime.now(clock)));
        View after = view(q);
        return WriteOutcome.of(customer.name() + " 견적 초안(" + String.format("%,d", total) + "원)을 씁니다",
                new Change("create", "quote", q.getId(), null, json(after)), true, after, q.getId());
    }

    /** 초안 되돌리기: 아직 draft면 cancelled로 둡니다. */
    public WriteOutcome undoCreate(String id) {
        Quote q = quotes.lockById(id).orElseThrow();
        if (!"draft".equals(q.getStatus())) {
            throw new ApiException(409, "undo-conflict", "그사이 견적이 발행돼 실행 취소할 수 없습니다.");
        }
        return change(q, "cancelled", null, "견적 초안을 취소했습니다");
    }

    public WriteOutcome issue(ErpPrincipal p, String id, int version) {
        requireFeature();
        Quote q = visible(p.employeeId(), quotes.lockById(id).orElse(null));
        if (!org.isSalesRep(p.employeeId())) {
            throw ApiException.forbidden("견적 발행은 영업 담당만 할 수 있습니다.");
        }
        if (version != q.getVersion()) {
            throw new ApiException(409, "version-conflict", "그사이 견적이 바뀌었습니다. 새로 고친 뒤 다시 시도하세요.");
        }
        if (!"draft".equals(q.getStatus())) {
            throw new ApiException(409, "invalid-state", "issued".equals(q.getStatus()) ? "이미 발행한 견적입니다."
                    : Ko.quoteStatus(q.getStatus()) + "된 견적은 발행할 수 없습니다.");
        }
        if (q.getValidUntil().isBefore(LocalDate.now(clock.withZone(zone)))) {
            throw new ApiException(409, "invalid-state", "유효 기한이 지나 발행할 수 없습니다. 유효 기한을 고쳐 새 견적을 쓰세요.");
        }
        return change(q, "issued", p.employeeId(), q.getCustomerName() + " 견적을 발행합니다");
    }

    private WriteOutcome change(Quote q, String status, String by, String summary) {
        JsonNode before = json(view(q));
        q.changeStatus(status, by, OffsetDateTime.now(clock));
        View after = view(quotes.saveAndFlush(q));
        return WriteOutcome.of(summary, new Change("update", "quote", q.getId(), before, json(after)), false, after,
                q.getId());
    }

    private Quote visible(String employeeId, Quote q) {
        if (q == null || !(q.getCreatedBy().equals(employeeId) || org.isSalesRep(employeeId))) {
            throw ApiException.notFound("견적이 없습니다");
        }
        return q;
    }

    private View view(Quote q) {
        List<Line> lines = mapper.convertValue(q.getLines(),
                mapper.getTypeFactory().constructCollectionType(List.class, Line.class));
        return new View(q.getId(), q.getCreatedBy(), q.getCustomerId(), q.getCustomerName(), lines,
                q.getTotalAmount(), q.getValidUntil(), q.getNote(), q.getStatus(), q.getVersion(), q.getIssuedBy(),
                q.getCreatedAt().atZoneSameInstant(zone).toOffsetDateTime(),
                q.getUpdatedAt().atZoneSameInstant(zone).toOffsetDateTime());
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }
}
