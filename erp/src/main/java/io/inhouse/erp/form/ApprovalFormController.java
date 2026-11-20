package io.inhouse.erp.form;

import io.inhouse.erp.auth.RequiredScope;
import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.org.OrgViews.Items;
import io.inhouse.erp.pack.Pack;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ApprovalFormController {

    public record FormView(String id, String name, JsonNode fieldsSchema, String amountField) {}

    private final ApprovalFormRepository forms;
    private final Set<String> enabled;

    public ApprovalFormController(ApprovalFormRepository forms, Pack pack) {
        this.forms = forms;
        this.enabled = pack.forms().stream().map(Pack.FormDef::id).collect(Collectors.toUnmodifiableSet());
    }

    @GetMapping("/approval-forms")
    @RequiredScope("approval:read")
    @Transactional(readOnly = true)
    public Items<FormView> list() {
        // DB에는 예전에 켰던 양식이 남을 수 있어 지금 단계(ERP_STAGE)에서 켠 양식만 냅니다.
        return new Items<>(forms.findAllByOrderBySortOrder().stream()
                .filter(f -> enabled.contains(f.getId()))
                .map(f -> new FormView(f.getId(), f.getName(), f.getFieldsSchema(), f.getAmountField()))
                .toList());
    }
}
