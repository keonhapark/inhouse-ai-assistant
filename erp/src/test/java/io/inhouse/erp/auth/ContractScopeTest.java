package io.inhouse.erp.auth;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import io.inhouse.erp.PostgresTestBase;
import java.io.File;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.mvc.method.RequestMappingInfo;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

/** 구현한 모든 경로가 계약(erp.yaml)에 있고, scope·사람 화면 전용 표시가 계약과 같은지 봅니다. */
class ContractScopeTest extends PostgresTestBase {

    @Autowired
    @Qualifier("requestMappingHandlerMapping")
    RequestMappingHandlerMapping mapping;

    @Test
    void handlersMatchContractScopes() throws Exception {
        JsonNode paths = new ObjectMapper(new YAMLFactory())
                .readTree(new File("../contracts/openapi/erp.yaml")).path("paths");
        List<String> problems = new ArrayList<>();
        int checked = 0;
        for (var e : mapping.getHandlerMethods().entrySet()) {
            RequestMappingInfo info = e.getKey();
            HandlerMethod hm = e.getValue();
            if (!hm.getBeanType().getPackageName().startsWith("io.inhouse.erp")
                    || hm.getBeanType().getSimpleName().endsWith("ProbeController")) {
                continue;
            }
            if (info.getMethodsCondition().getMethods().isEmpty()) {
                problems.add(hm + ": HTTP 메서드가 정해지지 않은 매핑");
            }
            for (String path : info.getPathPatternsCondition().getPatternValues()) {
                for (var method : info.getMethodsCondition().getMethods()) {
                    JsonNode op = paths.path(path).path(method.name().toLowerCase());
                    String where = method + " " + path;
                    if (op.isMissingNode()) {
                        problems.add(where + ": 계약에 없는 경로");
                        continue;
                    }
                    checked++;
                    RequiredScope rs = hm.getMethodAnnotation(RequiredScope.class);
                    String want = op.path("x-required-scope").asText(null);
                    boolean humanOnly = op.path("x-human-only").asBoolean(false);
                    boolean isPublic = hm.hasMethodAnnotation(PublicEndpoint.class);
                    boolean contractPublic = op.path("security").isArray() && op.path("security").isEmpty();
                    if (isPublic != contractPublic) {
                        problems.add(where + ": @PublicEndpoint와 계약 security: []가 다름");
                    }
                    if (want == null) {
                        if (rs != null) {
                            problems.add(where + ": 계약에 scope가 없는데 @RequiredScope가 있음");
                        }
                    } else if (rs == null) {
                        problems.add(where + ": @RequiredScope 없음(계약 " + want + ")");
                    } else if (!rs.value().equals(want) || rs.humanOnly() != humanOnly) {
                        problems.add(where + ": " + rs.value() + "/" + rs.humanOnly() + " != " + want + "/" + humanOnly);
                    }
                }
            }
        }
        assertThat(problems).isEmpty();
        assertThat(checked).isGreaterThanOrEqualTo(8);
    }
}
