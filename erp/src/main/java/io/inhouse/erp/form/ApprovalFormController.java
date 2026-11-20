package io.inhouse.erp.form;

import io.inhouse.erp.auth.RequiredScope;
import com.fasterxml.jackson.databind.JsonNode;
import io.inhouse.erp.org.OrgViews.Items;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ApprovalFormController {

    public record FormView(String id, String name, JsonNode fieldsSchema, String amountField) {}

    private final ApprovalFormRepository forms;

    public ApprovalFormController(ApprovalFormRepository forms) {
        this.forms = forms;
    }

    @GetMapping("/approval-forms")
    @RequiredScope("approval:read")
    @Transactional(readOnly = true)
    public Items<FormView> list() {
        return new Items<>(forms.findAllByOrderBySortOrder().stream()
                .map(f -> new FormView(f.getId(), f.getName(), f.getFieldsSchema(), f.getAmountField()))
                .toList());
    }
}
