package io.inhouse.erp.web;

import static org.assertj.core.api.Assertions.assertThat;

import io.inhouse.erp.ApiTestBase;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;

@ExtendWith(OutputCaptureExtension.class)
class AccessLogFilterTest extends ApiTestBase {

    @Test
    void logsOneLinePerRequestWithoutQueryOrToken(CapturedOutput out) throws Exception {
        String emp = members("sales").get(0);
        get("/approval-documents", emp, "box", "outbox");
        get("/tickets/tkt_none", emp);
        assertThat(out.getOut()).contains("access", "GET /approval-documents 200 ", "GET /tickets/tkt_none 404 ");
        assertThat(out.getOut()).doesNotContain("box=outbox").doesNotContain("Bearer");
    }
}
