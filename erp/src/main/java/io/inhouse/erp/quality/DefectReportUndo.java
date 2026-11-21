package io.inhouse.erp.quality;

import io.inhouse.erp.write.Action;
import io.inhouse.erp.write.UndoHandler;
import io.inhouse.erp.write.WriteOutcome;
import org.springframework.stereotype.Component;

/** 불량 보고서 초안 되돌리기(취소). 확정은 되돌리지 않습니다. */
@Component
class DefectReportUndo implements UndoHandler {

    private final DefectReportService reports;

    DefectReportUndo(DefectReportService reports) {
        this.reports = reports;
    }

    @Override
    public String operation() {
        return "createDefectReport";
    }

    @Override
    public WriteOutcome undo(Action original) {
        return reports.undoCreate(original.getResourceId());
    }
}
