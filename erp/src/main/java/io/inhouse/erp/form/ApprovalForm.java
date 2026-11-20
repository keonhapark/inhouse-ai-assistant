package io.inhouse.erp.form;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

/** 결재 양식. 팩 forms.yaml에서 적재합니다. 결재선·효과 규칙은 팩(Pack.FormDef)에서 바로 읽습니다. */
@Entity
@Table(name = "approval_form")
public class ApprovalForm {

    @Id
    private String id;
    private String name;
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "fields_schema")
    private JsonNode fieldsSchema;
    @Column(name = "amount_field")
    private String amountField;
    @Column(name = "sort_order")
    private int sortOrder;

    protected ApprovalForm() {}

    public ApprovalForm(String id) {
        this.id = id;
    }

    public void update(String name, JsonNode fieldsSchema, String amountField, int sortOrder) {
        this.name = name;
        this.fieldsSchema = fieldsSchema;
        this.amountField = amountField;
        this.sortOrder = sortOrder;
    }

    public String getId() { return id; }
    public String getName() { return name; }
    public JsonNode getFieldsSchema() { return fieldsSchema; }
    public String getAmountField() { return amountField; }
}
