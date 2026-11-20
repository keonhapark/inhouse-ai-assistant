package io.inhouse.erp.pack;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/** PACK_DIR의 pack.yaml·org.yaml·forms.yaml·fixtures/*.json을 읽어 {@link Pack}으로 만듭니다. */
public final class PackLoader {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory());
    private static final ObjectMapper JSON = new ObjectMapper();

    private PackLoader() {}

    public static Pack load(Path dir) {
        if (!Files.isDirectory(dir)) {
            throw new IllegalStateException("팩 폴더가 없습니다: " + dir.toAbsolutePath());
        }
        JsonNode pack = read(YAML, dir.resolve("pack.yaml"));
        JsonNode org = read(YAML, dir.resolve("org.yaml"));
        JsonNode forms = read(YAML, dir.resolve("forms.yaml"));
        JsonNode emps = read(JSON, dir.resolve("fixtures/employees.json"));
        JsonNode rooms = read(JSON, dir.resolve("fixtures/rooms.json"));
        JsonNode bals = read(JSON, dir.resolve("fixtures/leave_balances.json"));
        Path ticketsFile = dir.resolve("fixtures/tickets.json");
        JsonNode tickets = Files.exists(ticketsFile) ? read(JSON, ticketsFile) : JSON.createObjectNode();

        String tz = pack.path("company").path("timezone").asText("Asia/Seoul");
        JsonNode policy = org.path("delegation_policy");
        int stage = pack.path("stage").asInt(0);
        if (stage < 1) {
            throw new IllegalStateException("pack.yaml에 stage(1 이상)가 없습니다: " + dir.toAbsolutePath());
        }
        return new Pack(
                pack.path("id").asText(),
                stage,
                ZoneId.of(tz),
                list(org.path("grades"), g -> new Pack.Grade(g.path("id").asText(), g.path("name").asText(),
                        g.path("rank").asInt())),
                list(org.path("units"), u -> new Pack.UnitDef(u.path("id").asText(), u.path("name").asText(),
                        u.path("kind").asText(), textOrNull(u, "parent"))),
                list(org.path("roles"), r -> new Pack.RoleDef(r.path("id").asText(), r.path("name").asText(),
                        grant(r.path("grant")))),
                list(org.path("access_tags"), t -> new Pack.AccessTagDef(t.path("id").asText(),
                        t.path("name").asText(), grant(t.path("grant")))),
                new Pack.ErpRoles(org.path("erp_roles").path("hr").asText(Pack.ErpRoles.DEFAULT.hr()),
                        org.path("erp_roles").path("auditor").asText(Pack.ErpRoles.DEFAULT.auditor()),
                        org.path("erp_roles").path("ticket_handler").asText(Pack.ErpRoles.DEFAULT.ticketHandler())),
                new Pack.DelegationPolicy(policy.path("max_period_days").asInt(30),
                        strings(policy.path("registrable_by"))),
                list(forms.path("forms"), PackLoader::form),
                list(emps.path("employees"), e -> new Pack.EmployeeDef(e.path("id").asText(),
                        e.path("employee_no").asText(), e.path("name").asText(), e.path("unit_id").asText(),
                        e.path("grade").asText(), e.path("email").asText(),
                        LocalDate.parse(e.path("hired_on").asText()))),
                list(rooms.path("rooms"), r -> new Pack.RoomDef(r.path("id").asText(), r.path("name").asText(),
                        r.path("floor").asInt(), r.path("capacity").asInt())),
                list(bals.path("balances"), b -> new Pack.BalanceDef(b.path("employee_id").asText(),
                        b.path("year").asInt(), b.path("annual_total").asDouble(),
                        b.path("annual_used").asDouble())),
                list(tickets.path("tickets"), PackLoader::ticket));
    }

    private static Pack.TicketDef ticket(JsonNode t) {
        return new Pack.TicketDef(t.path("id").asText(), t.path("requester_id").asText(), t.path("category").asText(),
                t.path("priority").asText(), t.path("title").asText(), t.path("description").asText(),
                t.path("status").asText(), OffsetDateTime.parse(t.path("created_at").asText()),
                list(t.path("comments"), c -> new Pack.CommentDef(c.path("author_id").asText(),
                        c.path("body").asText(), OffsetDateTime.parse(c.path("created_at").asText()))));
    }

    private static Pack.FormDef form(JsonNode f) {
        Map<String, String> effects = new LinkedHashMap<>();
        f.path("effects").properties().forEach(e -> effects.put(e.getKey(), e.getValue().asText()));
        List<Pack.LineRule> line = list(f.path("approval_line"), r -> {
            JsonNode w = r.path("when");
            return new Pack.LineRule(longOrNull(w, "amount_lte"), longOrNull(w, "amount_gt"),
                    strings(r.path("steps")));
        });
        return new Pack.FormDef(f.path("id").asText(), f.path("name").asText(), f.path("stage").asInt(1),
                f.path("fields").deepCopy(),
                textOrNull(f, "amount_field"), effects, line);
    }

    private static Grant grant(JsonNode g) {
        if (g.isTextual() && g.asText().equals("all")) {
            return Grant.ALL;
        }
        return new Grant(false, set(g.path("units")), set(g.path("grades")), set(g.path("roles")));
    }

    private static JsonNode read(ObjectMapper mapper, Path file) {
        try {
            return mapper.readTree(file.toFile());
        } catch (IOException e) {
            throw new UncheckedIOException("팩 파일을 읽지 못했습니다: " + file, e);
        }
    }

    private static <T> List<T> list(JsonNode arr, Function<JsonNode, T> fn) {
        List<T> out = new ArrayList<>();
        arr.forEach(n -> out.add(fn.apply(n)));
        return List.copyOf(out);
    }

    private static List<String> strings(JsonNode arr) {
        return list(arr, JsonNode::asText);
    }

    private static Set<String> set(JsonNode arr) {
        return Set.copyOf(new LinkedHashSet<>(strings(arr)));
    }

    private static String textOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asText();
    }

    private static Long longOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asLong();
    }
}
