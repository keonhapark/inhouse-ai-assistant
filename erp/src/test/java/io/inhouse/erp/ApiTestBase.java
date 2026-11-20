package io.inhouse.erp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.nimbusds.jwt.JWTClaimsSet;
import io.inhouse.erp.auth.Tokens;
import io.inhouse.erp.pack.Pack;
import java.util.Date;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;

/** HTTP 수준 시험의 공통 도우미. 직원은 팩 고정 데이터에서 고릅니다. */
@AutoConfigureMockMvc
public abstract class ApiTestBase extends PostgresTestBase {

    @Autowired protected MockMvc mvc;
    @Autowired protected ObjectMapper mapper;
    @Autowired protected Pack pack;

    protected String jwt(String emp) {
        return Tokens.hs256(new JWTClaimsSet.Builder().issuer("erp").audience("erp").subject(emp)
                .expirationTime(new Date(System.currentTimeMillis() + 600_000)).build(), JWT_SECRET);
    }

    protected MockHttpServletResponse get(String path, String emp, String... params) throws Exception {
        var b = MockMvcRequestBuilders.get(path).header("Authorization", "Bearer " + jwt(emp));
        for (int i = 0; i + 1 < params.length; i += 2) {
            b.param(params[i], params[i + 1]);
        }
        return mvc.perform(b).andReturn().getResponse();
    }

    protected MockHttpServletResponse post(String path, String emp, Object body) throws Exception {
        return mvc.perform(MockMvcRequestBuilders.post(path).header("Authorization", "Bearer " + jwt(emp))
                .header("Idempotency-Key", UUID.randomUUID().toString())
                .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(body)))
                .andReturn().getResponse();
    }

    protected JsonNode json(MockHttpServletResponse r) throws Exception {
        return mapper.readTree(r.getContentAsString());
    }

    protected String problem(MockHttpServletResponse r) throws Exception {
        return json(r).path("type").asText().replace("urn:problem:", "");
    }

    protected String leader(String unit) {
        return pack.employees().stream().filter(e -> e.unitId().equals(unit) && pack.isHeadGrade(e.grade()))
                .findFirst().orElseThrow().id();
    }

    protected java.util.List<String> members(String unit) {
        return pack.employees().stream().filter(e -> e.unitId().equals(unit) && !pack.isHeadGrade(e.grade()))
                .map(Pack.EmployeeDef::id).toList();
    }
}
