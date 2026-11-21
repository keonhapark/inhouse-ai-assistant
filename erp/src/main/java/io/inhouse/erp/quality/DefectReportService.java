package io.inhouse.erp.quality;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.auth.ErpPrincipal;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Ids;
import io.inhouse.erp.org.OrgService;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.write.Change;
import io.inhouse.erp.write.WriteOutcome;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.List;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 불량 보고서(계약 erp.yaml quality). 팩 기능 quality가 없으면 404입니다. 쓴 사람과 품질 확인 역할(팩
 * erp_roles.quality_reviewer)만 보고, 확정은 그 역할만 사람 화면에서 합니다(ScopeGuard가 위임 토큰을 막음).
 */
@Service
public class DefectReportService {

    static final String FEATURE = "quality";

    public record View(String id, String createdBy, String itemCode, String itemName, String defectType,
                       String severity, int quantity, String location, String lotNo, String description,
                       String status, int version, String confirmedBy, OffsetDateTime createdAt,
                       OffsetDateTime updatedAt) {}

    public record CreateRequest(String itemCode, String defectType, String severity, int quantity, String location,
                                String lotNo, String description) {}

    private final DefectReportRepository reports;
    private final OrgService org;
    private final Pack pack;
    private final ObjectMapper mapper;
    private final ZoneId zone;
    private final Clock clock;

    public DefectReportService(DefectReportRepository reports, OrgService org, Pack pack, ObjectMapper mapper,
                               Clock clock) {
        this.reports = reports;
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

    @Transactional(readOnly = true)
    public List<View> list(String employeeId, String box, String status, int limit) {
        requireFeature();
        if (!"mine".equals(box) && !"all".equals(box)) {
            throw ApiException.validation("box", "mine, all 중 하나");
        }
        if (status != null && !DefectReport.STATUSES.contains(status)) {
            throw ApiException.validation("status", "unknown");
        }
        if ("all".equals(box) && !org.isQualityReviewer(employeeId)) {
            throw ApiException.forbidden("품질 확인 역할만 전체를 봅니다");
        }
        return reports.search("mine".equals(box) ? employeeId : null, status,
                Limit.of(Math.max(1, Math.min(limit, 100)))).stream().map(this::view).toList();
    }

    @Transactional(readOnly = true)
    public View get(String employeeId, String id) {
        requireFeature();
        return view(visible(employeeId, reports.findById(id).orElse(null)));
    }

    public WriteOutcome create(ErpPrincipal p, CreateRequest req) {
        requireFeature();
        Pack.ItemDef item = pack.item(req.itemCode()).orElseThrow(() -> ApiException.validation("itemCode", "unknown"));
        DefectReport d = reports.saveAndFlush(new DefectReport(Ids.next("dfr"), p.employeeId(), item.code(),
                item.name(), req.defectType(), req.severity(), req.quantity(), req.location(), req.lotNo(),
                req.description(), "draft", null, OffsetDateTime.now(clock)));
        View after = view(d);
        return WriteOutcome.of(item.name() + " 불량 보고서 초안을 씁니다",
                new Change("create", "defect_report", d.getId(), null, json(after)), true, after, d.getId());
    }

    /** 초안 되돌리기: 아직 draft면 cancelled로 둡니다. */
    public WriteOutcome undoCreate(String id) {
        DefectReport d = reports.lockById(id).orElseThrow();
        if (!"draft".equals(d.getStatus())) {
            throw new ApiException(409, "undo-conflict", "그사이 확정되었습니다");
        }
        return change(d, "cancelled", null, "불량 보고서 초안을 되돌렸습니다(취소)", false);
    }

    public WriteOutcome confirm(ErpPrincipal p, String id, int version) {
        requireFeature();
        DefectReport d = visible(p.employeeId(), reports.lockById(id).orElse(null));
        if (!org.isQualityReviewer(p.employeeId())) {
            throw ApiException.forbidden("품질 확인 역할만 확정합니다");
        }
        if (version != d.getVersion()) {
            throw new ApiException(409, "version-conflict", "그사이 보고서가 바뀌었습니다");
        }
        if (!"draft".equals(d.getStatus())) {
            throw new ApiException(409, "invalid-state", d.getStatus() + " 보고서는 확정할 수 없습니다");
        }
        return change(d, "confirmed", p.employeeId(), d.getItemName() + " 불량 보고서를 확정합니다", false);
    }

    private WriteOutcome change(DefectReport d, String status, String by, String summary, boolean undoable) {
        JsonNode before = json(view(d));
        d.changeStatus(status, by, OffsetDateTime.now(clock));
        View after = view(reports.saveAndFlush(d));
        return WriteOutcome.of(summary, new Change("update", "defect_report", d.getId(), before, json(after)), undoable,
                after, d.getId());
    }

    private DefectReport visible(String employeeId, DefectReport d) {
        if (d == null || !(d.getCreatedBy().equals(employeeId) || org.isQualityReviewer(employeeId))) {
            throw ApiException.notFound("불량 보고서가 없습니다");
        }
        return d;
    }

    private View view(DefectReport d) {
        return new View(d.getId(), d.getCreatedBy(), d.getItemCode(), d.getItemName(), d.getDefectType(),
                d.getSeverity(), d.getQuantity(), d.getLocation(), d.getLotNo(), d.getDescription(), d.getStatus(),
                d.getVersion(), d.getConfirmedBy(), at(d.getCreatedAt()), at(d.getUpdatedAt()));
    }

    private OffsetDateTime at(OffsetDateTime t) {
        return t.atZoneSameInstant(zone).toOffsetDateTime();
    }

    private JsonNode json(Object o) {
        return mapper.valueToTree(o);
    }

    /** 팩 고정 불량 보고서를 없는 것만 넣습니다(평가 초기화 뒤에도). */
    public int seed(List<Pack.DefectReportDef> defs) {
        int added = 0;
        for (Pack.DefectReportDef f : defs) {
            if (reports.existsById(f.id())) {
                continue;
            }
            String name = pack.item(f.itemCode()).map(Pack.ItemDef::name).orElse(f.itemCode());
            reports.save(new DefectReport(f.id(), f.createdBy(), f.itemCode(), name, f.defectType(), f.severity(),
                    f.quantity(), f.location(), f.lotNo(), f.description(), f.status(), f.confirmedBy(), f.createdAt()));
            added++;
        }
        reports.flush();
        return added;
    }
}
