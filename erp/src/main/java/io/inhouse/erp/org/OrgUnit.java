package io.inhouse.erp.org;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "org_unit")
public class OrgUnit {

    @Id
    private String id;
    private String name;
    private String kind;
    @Column(name = "parent_id")
    private String parentId;
    @Column(name = "head_id")
    private String headId;
    @Column(name = "sort_order")
    private int sortOrder;

    protected OrgUnit() {}

    public OrgUnit(String id, String name, String kind, String parentId, String headId, int sortOrder) {
        this.id = id;
        update(name, kind, parentId, headId, sortOrder);
    }

    public void update(String name, String kind, String parentId, String headId, int sortOrder) {
        this.name = name;
        this.kind = kind;
        this.parentId = parentId;
        this.headId = headId;
        this.sortOrder = sortOrder;
    }

    public String getId() { return id; }
    public String getName() { return name; }
    public String getKind() { return kind; }
    public String getParentId() { return parentId; }
    public String getHeadId() { return headId; }
    public boolean isTeam() { return "team".equals(kind); }
}
