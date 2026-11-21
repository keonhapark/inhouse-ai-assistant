package io.inhouse.erp.sales;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.ApiTestBase;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.pack.Pack;
import io.inhouse.erp.pack.PackLoader;
import io.inhouse.erp.quality.DefectReportService;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockHttpServletResponse;

/** 품질·영업: 팩 고정 데이터, 기능이 없으면 404, 동시 확정, 견적 금액 계산. 계약 행동 시험과 겹치지 않는 것만. */
class QualitySalesTest extends ApiTestBase {

    @Test
    void packFixturesAreServed() throws Exception {
        String reviewer = members("quality").get(0);
        JsonNode d = json(get("/quality/defect-reports/dfr_0002", reviewer));
        assertThat(d.path("status").asText()).isEqualTo("confirmed");
        assertThat(d.path("itemName").asText()).isEqualTo("정밀 샤프트 20x400");
        assertThat(json(get("/items", reviewer, "q", "베어링")).path("items").findValuesAsText("code"))
                .containsExactly("BRG-6204", "BRG-6205");
    }

    @Test
    void featureOffMeansNotFound(@TempDir Path tmp) throws IOException {
        Path pack = Path.of("../packs/manufacturing");
        try (Stream<Path> files = Files.walk(pack)) {
            for (Path src : files.toList()) {
                Path dst = tmp.resolve(pack.relativize(src).toString());
                if (Files.isDirectory(src)) {
                    Files.createDirectories(dst);
                } else {
                    Files.copy(src, dst);
                }
            }
        }
        Path y = tmp.resolve("pack.yaml");
        Files.writeString(y, Files.readString(y).replaceAll("(?m)^  - (quality|sales)\\n", ""));
        Pack off = PackLoader.load(tmp);
        assertThat(off.hasFeature("quality")).isFalse();
        QuoteService quotes = new QuoteService(null, null, off, new ObjectMapper(), null);
        DefectReportService defects = new DefectReportService(null, null, off, new ObjectMapper(), null);
        for (Runnable r : List.<Runnable>of(quotes::requireFeature, defects::requireFeature)) {
            assertThatThrownBy(r::run)
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(404));
        }
        assertThat(quotes.items(null, 100)).hasSize(12);  // 품목은 기능과 관계없이
    }

    @Test
    void concurrentConfirmationsOneWins() throws Exception {
        MockHttpServletResponse created = post("/quality/defect-reports", members("production-control").get(0),
                Map.of("itemCode", "NUT-M8", "defectType", "나사산 불량", "severity", "minor", "quantity", 50,
                        "description", "탭 불량"));
        assertThat(created.getStatus()).as(created.getContentAsString()).isEqualTo(201);
        String id = json(created).path("resource").path("id").asText();
        List<String> reviewers = members("quality");
        ExecutorService pool = Executors.newFixedThreadPool(reviewers.size());
        try {
            List<Callable<MockHttpServletResponse>> calls = reviewers.stream()
                    .<Callable<MockHttpServletResponse>>map(r -> () -> post("/quality/defect-reports/" + id + "/confirm",
                            r, Map.of("version", 0)))
                    .toList();
            int ok = 0;
            for (Future<MockHttpServletResponse> f : pool.invokeAll(calls)) {
                MockHttpServletResponse r = f.get();
                if (r.getStatus() == 201) {
                    ok++;
                } else {
                    assertThat(problem(r)).isEqualTo("version-conflict");
                }
            }
            assertThat(ok).isEqualTo(1);
        } finally {
            pool.shutdown();
        }
    }

    @Test
    void quoteUsesItemPricesNotClientInput() throws Exception {
        MockHttpServletResponse r = post("/sales/quotes", members("sales").get(0), Map.of("customerId", "cus_0002",
                "lines", List.of(Map.of("itemCode", "PLT-S304-2", "quantity", 1_000_000), Map.of("itemCode", "NUT-M8",
                        "quantity", 7))));
        assertThat(r.getStatus()).as(r.getContentAsString()).isEqualTo(201);
        JsonNode q = json(r).path("resource");
        assertThat(q.path("totalAmount").asLong()).isEqualTo(1_000_000L * 84_000 + 7 * 45);
        assertThat(problem(post("/sales/quotes", members("sales").get(0), Map.of("customerId", "cus_0002",
                "lines", List.of(Map.of("itemCode", "NUT-M8", "quantity", 1, "unitPrice", 1)))))).isEqualTo("validation");
    }
}
