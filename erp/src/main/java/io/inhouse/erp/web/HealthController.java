package io.inhouse.erp.web;

import io.inhouse.erp.auth.PublicEndpoint;
import io.inhouse.erp.common.OperationId;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HealthController {

    @GetMapping("/health")
    @OperationId("health")
    @PublicEndpoint
    public Map<String, String> health() {
        return Map.of("status", "ok");
    }
}
